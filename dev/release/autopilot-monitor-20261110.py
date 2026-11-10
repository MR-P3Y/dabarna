#!/usr/bin/env python3
"""Host-only monitor: read-only game checks, durable history, deduplicated Telegram alerts.

No database writes, game calls, wallet changes, or Docker service restarts.
Requires root cron, installed companion audit shell script, and the existing bot.
"""
from __future__ import annotations
import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

STATE_DIR = Path("/var/lib/davarna-autopilot-monitor")
RUNNER = Path("/usr/local/sbin/davarna-autopilot-health-audit.sh")
HISTORY = STATE_DIR / "history.jsonl"
STATE = STATE_DIR / "state.json"
LOCK = STATE_DIR / "monitor.lock"
RENOTIFY_SECONDS = 6 * 3600
MAX_OUTPUT = 90000
ERROR_PATTERN = re.compile(r"^ALERT\s+([A-Z_]+):\s*(.{0,300})$",re.M)
LOG_PATTERN = re.compile(r"^(davarna-backend|davarna-bot) critical_log_matches=(\d+)$",re.M)

def utcnow():
    return dt.datetime.now(dt.timezone.utc)

def load_state():
    if not STATE.exists():
        return {"open":{}}
    value=json.loads(STATE.read_text(encoding="utf-8"))
    if not isinstance(value,dict) or not isinstance(value.get("open"),dict):
        raise ValueError("monitor state invalid; not resetting alert ACKs")
    return value

def save_state(value):
    fd,tmp=tempfile.mkstemp(prefix=".monitor-state-",dir=str(STATE_DIR))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            json.dump(value,out,ensure_ascii=False,sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp,STATE)
        dfd=os.open(str(STATE_DIR),os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
        try:os.fsync(dfd)
        finally:os.close(dfd)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def send_topic(message):
    # Telegram token and chat/thread IDs are read only within the bot container;
    # they are never written to host logs, commands or files.
    sender="""
import asyncio,sys
from aiogram import Bot
from bot.config import settings
from bot.services.admin_topics import send_to_topic
async def main():
    token=settings.TELEGRAM_BOT_TOKEN
    assert token,"bot token missing"
    bot=Bot(token=token)
    try:
        return await send_to_topic(bot,name="alerts",text=sys.stdin.read(),parse_mode="HTML",disable_notification=False)
    finally:
        await bot.session.close()
print("DELIVERED" if asyncio.run(main()) else "NOT_DELIVERED")
"""
    try:
        r=subprocess.run(["docker","exec","-i","davarna-bot","python","-c",sender],input=message,
                         text=True,capture_output=True,timeout=25)
        return r.returncode==0 and r.stdout.strip()=="DELIVERED"
    except (subprocess.SubprocessError,OSError):
        return False

def analyze_report(report, exit_code):
    findings={}
    for kind,detail in ERROR_PATTERN.findall(report):
        # Each issue identity is stable across polling until the specific game/level changes.
        # Avoid dynamically varying numbers in the key (age/seconds/cursor).
        identity=re.search(r"\b(?:game|level|last_ended_id)=([A-Z0-9]+)",detail)
        lane=re.match(r"^(LOW|MEDIUM|HIGH)\b",detail)
        suffix=identity.group(1) if identity else (lane.group(1) if lane else "GLOBAL")
        findings[f"{kind}:{suffix}"]=f"{kind}: {detail[:220]}"
    for service,count in LOG_PATTERN.findall(report):
        if int(count)>0:
            findings[f"RECENT_WORKER_LOG_ERRORS:{service}"]=f"{service}: {count} recent critical log matches"
    if exit_code!=0 or "===== READ-ONLY SNAPSHOT COMPLETE =====" not in report:
        findings["MONITOR_COLLECTION_FAILED:GLOBAL"]=f"Health audit failed (exit_code={exit_code}); verify containers and host logs"
    return findings

def transition(previous, findings, now_ts):
    """Pure dedup selector, intentionally without side effects for isolated tests."""
    old=previous.get("open",{})
    new={}
    notifications=[]
    for key,message in findings.items():
        prior=old.get(key,{})
        last=float(prior.get("last_sent",0))
        new[key]={"first_seen":prior.get("first_seen",now_ts),
                  "last_sent":last,"message":message}
        if not prior or now_ts-last>=RENOTIFY_SECONDS:
            notifications.append(("ALERT",key,message))
    for key,prior in old.items():
        if key not in new and float(prior.get("last_sent",0))>0:
            # Unacknowledged recovery notices remain pending across checks.
            notifications.append(("RESOLVED",key,prior.get("message",key)))
            new[key]={"first_seen":prior.get("first_seen",now_ts),
                      "last_sent":prior.get("last_sent",0),
                      "message":prior.get("message",key),"pending_resolution":True}
    for key,prior in old.items():
        if prior.get("pending_resolution") and key not in findings:
            if not any(event[1]==key for event in notifications):
                notifications.append(("RESOLVED",key,prior.get("message",key)))
    return {"open":new},notifications

def persist_history(record):
    with HISTORY.open("a",encoding="utf-8") as h:
        h.write(json.dumps(record,ensure_ascii=False,separators=(",",":"))+"\n")
        h.flush()
        os.fsync(h.fileno())

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--dry-run",action="store_true",help="collect only; do not write state/history or send")
    parser.add_argument("--test-notification",action="store_true",help="send one alert channel setup test, no state/history")
    args=parser.parse_args()
    if args.dry_run and args.test_notification:
        parser.error("choose dry-run or test-notification")
    if os.geteuid()!=0:raise SystemExit("BLOCKER: root required")
    if args.test_notification:
        ok=send_topic("✅ آزمون کانال پایش دبرنا\\nاتصال اعلان مدیریت فعال شد. این پیام آزمایشی است.")
        print("TELEGRAM_TEST_DELIVERED" if ok else "TELEGRAM_TEST_FAILED")
        return 0 if ok else 2
    if not RUNNER.is_file():raise SystemExit("BLOCKER: audit runner not installed")
    STATE_DIR.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(STATE_DIR,0o700)
    with LOCK.open("a+") as guard:
        try:fcntl.flock(guard.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print("SKIPPED: previous monitor still running")
            return 0
        started=utcnow()
        try:
            r=subprocess.run(["bash",str(RUNNER)],capture_output=True,text=True,timeout=80)
            report=(r.stdout+"\n"+r.stderr)[:MAX_OUTPUT]
            status=r.returncode
        except subprocess.TimeoutExpired:
            report="AUDIT_TIMEOUT"
            status=124
        findings=analyze_report(report,status)
        print(f"CHECK_AT={started.isoformat()} EXIT={status} ALERTS={len(findings)}")
        for key,message in sorted(findings.items()):
            print(f"ALERT {key}: {message}")
        if args.dry_run:
            print("DRY_RUN: no state/history writes or Telegram sends")
            return 0 if status==0 else 2
        try:
            previous=load_state()
        except (ValueError,OSError,json.JSONDecodeError) as exc:
            print(f"BLOCKER: state unreadable: {type(exc).__name__}; no sends",file=sys.stderr)
            return 2
        state,events=transition(previous,findings,started.timestamp())
        sent=0
        failures=0
        delivered_events=set()
        for typ,key,message in events:
            # Keep message free of sensitive payment/user payloads; all details are operational IDs.
            safe=message.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            label="⚠️ هشدار پایش دبرنا" if typ=="ALERT" else "✅ رفع هشدار دبرنا"
            text=f"{label}\n<code>{key}</code>\n{safe}\nUTC {started:%Y-%m-%d %H:%M}"
            delivered=send_topic(text)
            if delivered:
                sent+=1
                delivered_events.add((typ,key))
                if typ=="ALERT" and key in state["open"]:
                    state["open"][key]["last_sent"]=started.timestamp()
            else:
                failures+=1
                print(f"DELIVERY_FAILED {typ} {key}",file=sys.stderr)
                # Never mark failed sends as ACKed; they will retry on next run.
        for typ,key,message in events:
            if typ=="RESOLVED" and (typ,key) in delivered_events:
                state["open"].pop(key,None)
            elif typ=="RESOLVED" and key in state["open"]:
                state["open"][key]["pending_resolution"]=True
        save_state(state)
        persist_history({"at":started.isoformat(),"collector_exit":status,
                         "findings":findings,"alerts":len(findings),
                         "notices_sent":sent,"delivery_failures":failures})
        print(f"PERSISTED history={HISTORY} sent={sent} send_failures={failures}")
        return 0 if status==0 and failures==0 else 2

if __name__=="__main__":
    raise SystemExit(main())
