#!/usr/bin/env bash
# Davarna V2: production read-only autopilot health snapshot.
# Never changes game state, financial records, Docker configuration or services.
set -Eeuo pipefail
umask 077
die(){ echo "BLOCKER: $*" >&2; exit 2; }
[[ "$(id -u)" == 0 ]] || die "root required"
for svc in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$svc")" || die "missing container $svc"
  printf 'CONTAINER %-18s %s\n' "$svc" "$health"
  [[ "$health" == healthy ]] || die "unhealthy $svc"
done

echo "===== ACTIVE SYSTEM GAME HEALTH / DATABASE READ ONLY ====="
docker exec -i davarna-backend python - <<'PY'
from collections import Counter
from datetime import datetime, timezone, timedelta
from sqlalchemy import select,func
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game import Game,GameAutoDraw,GameCalledNumber,GameCard
from app.models.game_autopilot import GameAutopilotConfig
from app.models.game_event import GameEvent
from app.services.game_autopilot_config_service import GameAutopilotConfigService as Config

now=datetime.now(timezone.utc).replace(tzinfo=None)
findings=[]
def alert(kind,info):
 findings.append((kind,info))
 print(f"ALERT {kind}: {info}")
def asutc(value):
 if value is None:return None
 if isinstance(value,datetime):
  return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
 try:
  dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
  return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
 except (ValueError,TypeError): return None
def age_s(value):
 dt=asutc(value)
 return int((now-dt).total_seconds()) if dt is not None else None

print("AUTO_DRAW:",bool(cfg.GAME_AUTO_DRAW_ENABLED))
print("AUTOPILOT:",bool(cfg.GAME_AUTOPILOT_RUNTIME_ENABLED))
print("TICK_SECONDS:",cfg.GAME_AUTOPILOT_TICK_SECONDS)
if not cfg.GAME_AUTO_DRAW_ENABLED or not cfg.GAME_AUTOPILOT_RUNTIME_ENABLED:
 alert("WORKER_DISABLED","one or both game workers are disabled")
expected={"LOW":6,"MEDIUM":8,"HIGH":10}
group=cfg.USER_FORUM_CHAT_ID or cfg.DEFAULT_TG_GROUP_ID
with SessionLocal() as db:
 configs={lvl:db.get(GameAutopilotConfig,lvl) for lvl in expected}
 active=db.execute(select(Game).where(Game.status.in_(("LOBBY","RUNNING"))).order_by(Game.id.desc())).scalars().all()
 print("ACTIVE_COUNT:",len(active))
 for lvl,topic in expected.items():
  conf=configs[lvl]
  if conf is None:
   alert("MISSING_CONFIG",lvl)
   continue
  actual_topic=Config.topic_id_for_level(lvl)
  enabled=bool(int(conf.enabled or 0))
  print(f"LANE {lvl}: enabled={enabled} topic={actual_topic} scheduler={conf.scheduler_mode} start={conf.start_mode} draw={conf.draw_mode} min_players={conf.min_unique_players}")
  if not enabled: alert("DISABLED_LANE",lvl)
  if actual_topic!=topic or str(conf.scheduler_mode)!="AUTO" or str(conf.start_mode)!="AUTO" or str(conf.draw_mode)!="AUTO":
   alert("CONFIG_DRIFT",lvl)
  matches=[g for g in active if str(g.game_level)==lvl or (g.game_level is None and int(g.tg_topic_id or 0)==topic)]
  if enabled and not matches:
   # Only flag missing system rounds after the configured repeat/cooldown and grace window.
   # This avoids false alarms during the normal gap between two rounds.
   latest=db.execute(select(Game).where(
     Game.tg_group_id==int(group or 0),
     Game.status=="ENDED",
     ((Game.game_level==lvl) | ((Game.game_level.is_(None)) & (Game.tg_topic_id==topic)))
   ).order_by(Game.ended_at.desc(),Game.id.desc()).limit(1)).scalars().first()
   if latest is not None:
    since=age_s(latest.ended_at or latest.created_at)
    wait_s=max(int(conf.cooldown_seconds or 0),int(conf.repeat_interval_seconds or 0))
    grace=max(120,5*int(cfg.GAME_AUTOPILOT_TICK_SECONDS))
    if since is not None and since>wait_s+grace:
     alert("MISSING_NEXT_ROUND",f"level={lvl} last_ended_id={latest.id} elapsed_s={since} configured_delay_s={wait_s}")
   else:
    alert("NO_ACTIVE_OR_ENDED_ROUND",f"level={lvl} enabled but no matching historical ENDED round")
  if len(matches)>1: alert("DUPLICATE_LANE",f"{lvl} games={[g.id for g in matches]}")
  for g in matches:
   if int(g.tg_topic_id or 0)!=topic or (group is not None and int(g.tg_group_id)!=int(group)):
    alert("WRONG_TOPIC",f"game={g.id} level={lvl}")
   a=db.get(GameAutoDraw,int(g.id))
   players=int(db.scalar(select(func.count(func.distinct(GameCard.user_id))).where(GameCard.game_id==g.id)) or 0)
   called=int(db.scalar(select(func.count(GameCalledNumber.id)).where(GameCalledNumber.game_id==g.id)) or 0)
   status=str(a.status) if a else "MISSING"
   cursor=int(a.cursor or 0) if a else None
   interval=int(a.interval_seconds or 0) if a else 0
   last_due=age_s(a.next_draw_at) if a else None
   print(f"GAME id={g.id} level={lvl} status={g.status} source={g.execution_source} draw={g.draw_mode} players={players} called={called} cursor={cursor} auto={status} next_due_age_s={last_due}")
   if str(g.execution_source)!="SYSTEM":
    print(f"INFO: manual game #{g.id} blocks auto scheduling for {lvl}")
    continue
   if str(g.draw_mode)!="AUTO" or a is None: alert("INVALID_AUTO",f"game={g.id}")
   if str(g.status)=="RUNNING":
    if status!="RUNNING": alert("STALLED_DRAW",f"game={g.id} auto_state={status}")
    elif a.next_draw_at is None: alert("MISSING_NEXT_DRAW",f"game={g.id}")
    elif last_due is not None and last_due>max(90,3*max(1,interval)+30):
     alert("OVERDUE_NUMBER",f"game={g.id} due_by={last_due}s interval={interval}s")
    if cursor is not None and cursor!=called:
     alert("CURSOR_MISMATCH",f"game={g.id} cursor={cursor} called={called}")
   elif str(g.status)=="LOBBY":
    if status not in ("ARMED","STOPPED"): alert("LOBBY_DRAW_STATE",f"game={g.id} auto={status}")
    minimum=max(2,int(conf.min_unique_players or 2))
    if players>=minimum:
     if not g.scheduled_start_at:
      created_age=age_s(g.created_at)
      if created_age is not None and created_age>max(90,3*int(cfg.GAME_AUTOPILOT_TICK_SECONDS)):
       alert("MISSING_COUNTDOWN",f"game={g.id} players={players}")
     else:
      overdue=age_s(g.scheduled_start_at)
      if overdue is not None and overdue>90:
       alert("OVERDUE_START",f"game={g.id} seconds={overdue}")
 # Orphaned or paused auto worker for RUNNING games, irrespective of lane.
 outside=db.execute(select(Game,GameAutoDraw).join(GameAutoDraw,Game.id==GameAutoDraw.game_id).where(
  Game.status=="RUNNING",Game.draw_mode=="AUTO"
 )).all()
 for game,control in outside:
  if str(control.status)!="RUNNING":
   alert("GLOBAL_DRAW_NOT_RUNNING",f"game={game.id} state={control.status}")
 # Previously ended rounds must not still draw.
 unexpected=db.execute(select(Game.id,GameAutoDraw.status).join(GameAutoDraw,Game.id==GameAutoDraw.game_id).where(
  Game.status=="ENDED",GameAutoDraw.status=="RUNNING"
 ).limit(20)).all()
 for gid,status in unexpected:alert("ENDED_DRAW_ACTIVE",f"game={gid} auto={status}")
 events=db.execute(select(GameEvent.id,GameEvent.game_id,GameEvent.kind).where(
  GameEvent.kind.in_(("ERROR","AUTO_DRAW_TAMPER_DETECTED"))
 ).order_by(GameEvent.id.desc()).limit(8)).all()
 print("LATEST_ERROR_EVENTS:",[(int(eid),int(gid),kind) for eid,gid,kind in events])
 recent=db.execute(select(GameEvent.id,GameEvent.game_id,GameEvent.kind).where(
  GameEvent.kind.in_(("ERROR","AUTO_DRAW_TAMPER_DETECTED")),
  GameEvent.created_at >= now-timedelta(minutes=15),
 ).order_by(GameEvent.id.desc()).limit(8)).all()
 for eid,gid,kind in recent:
  alert("RECENT_GAME_ERROR",f"game={int(gid)} event_id={int(eid)} kind={kind}")
 print("ALERT_COUNT:",len(findings))
 print("SUMMARY:", "PASS" if not findings else "REVIEW_REQUIRED")
PY

echo "===== RECENT WORKER ERROR COUNTS (15m) ====="
for svc in davarna-backend davarna-bot; do
  # This prints counts only; no tokens, message payloads or log contents.
  errors="$(docker logs --since 15m --tail 2000 "$svc" 2>&1 | grep -Eic 'auto draw worker cycle failed|automatic number draw failed|autopilot level cycle failed|game autopilot worker cycle failed|commitment mismatch|sequence exhausted|Traceback' || true)"
  printf '%s critical_log_matches=%s\n' "$svc" "$errors"
done
echo "===== READ-ONLY SNAPSHOT COMPLETE ====="
