#!/usr/bin/env bash
# One-time Telegram USER forum guide + READ-ONLY LOW/autopilot/payment diagnostics.
# The only intended mutation is one Telegram send/pin and its idempotency marker
# in Redis. No game creation, scheduler, financial operation or DB changes.
set -Eeuo pipefail
umask 077

ROOT=/opt/davarna-v2
SOURCE=e7517922f08685be99a8f55564da1ad22abeddac
BACKEND_TAG=davarna-backend:forum-mini-e7517922-stage2
BOT_TAG=davarna-bot:forum-mini-e7517922-stage2
BACKEND_ID=sha256:b6d2709c3f78ce946a90aeb1b2bd6774acfa6b72a88cd604c370842cc3824850
BOT_ID=sha256:dccabe74e0d5eaad8d2a2f7df8fc5d5b53a84cfe1d6f172475aaed8b93ca04e2
KEY=davarna:userforum:guide:v1:20261107

fail() { echo "BLOCKER: $*" >&2; exit 2; }
[[ "$(id -u)" == 0 ]] || fail "root required"
exec 9>/run/davarna-user-forum-guide.lock
flock -n 9 || fail "guide publication lock already held"

cd "$ROOT"
git cat-file -e "$SOURCE^{commit}" || fail "approved guide source unavailable"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] \
    || fail "production container unhealthy: $c"
done
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$BACKEND_TAG" ]] \
  || fail "unexpected deployed Backend tag"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == "$BOT_TAG" ]] \
  || fail "unexpected deployed Bot tag"
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$BACKEND_ID" ]] \
  || fail "deployed Backend image bytes differ"
[[ "$(docker inspect -f '{{.Image}}' davarna-bot)" == "$BOT_ID" ]] \
  || fail "deployed Bot image bytes differ"
[[ "$(curl -fsS --max-time 8 http://127.0.0.1:18080/health/db)" == '{"ok":true}' ]] \
  || fail "database health endpoint failed"

backend_audit() {
  docker exec -i davarna-backend python - <<'PY'
import hashlib, json
from sqlalchemy import func,select
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game import Game
from app.models.game_autopilot import GameAutopilotConfig
from app.models.settings import AppSetting
from app.services.game_autopilot_config_service import GameAutopilotConfigService
flags={
    "tambola_v2":bool(cfg.GAME_TAMBOLA_V2_ENABLED),
    "auto_draw":bool(cfg.GAME_AUTO_DRAW_ENABLED),
    "autopilot_runtime":bool(cfg.GAME_AUTOPILOT_RUNTIME_ENABLED),
}
if flags!={"tambola_v2":True,"auto_draw":False,"autopilot_runtime":False}:
    raise SystemExit("BLOCKER: game runtime flags do not match safe launch baseline")
topics={level:GameAutopilotConfigService.topic_id_for_level(level) for level in ("LOW","MEDIUM","HIGH")}
if not all(isinstance(x,int) and x>0 for x in topics.values()) or len(set(topics.values()))!=3:
    raise SystemExit("BLOCKER: backend level topics missing/duplicated")
if not cfg.USER_FORUM_CHAT_ID or int(cfg.USER_FORUM_CHAT_ID)>=0:
    raise SystemExit("BLOCKER: backend user forum group not configured")
with SessionLocal() as db:
    rev=db.connection().exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
    if str(rev)!="20261104_0011":
        raise SystemExit("BLOCKER: unexpected DB migration head")
    configs=db.execute(select(GameAutopilotConfig).order_by(GameAutopilotConfig.level)).scalars().all()
    config_map={x.level:GameAutopilotConfigService.serialize(x) for x in configs}
    if "LOW" not in config_map:
        raise SystemExit("BLOCKER: LOW autopilot configuration missing")
    active=db.execute(select(Game).where(Game.status.in_(["LOBBY","RUNNING"])).order_by(Game.id)).scalars().all()
    keys=["deposit_destinations","bank_deposit_enabled","crypto_payments_runtime_enabled"]
    finance={}
    for key in keys:
        row=db.get(AppSetting,key)
        finance[key]=row.v_json if row is not None else None
    protected={
        "flags":flags,
        "finance":finance,
        "crypto_tron":cfg.CRYPTO_TRON_USDT_ADDRESS,
        "crypto_ton":cfg.CRYPTO_TON_ADDRESS,
        "crypto_enabled":bool(cfg.CRYPTO_PAYMENTS_ENABLED),
        "configs":config_map,
        "topics":topics,
    }
    digest=hashlib.sha256(json.dumps(protected,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
    report={
        "group_id":cfg.USER_FORUM_CHAT_ID,
        "game_topics":topics,
        "runtime_flags":flags,
        "LOW":config_map["LOW"],
        "other_levels":{l:{"enabled":v["enabled"],"scheduler_mode":v["scheduler_mode"]}
             for l,v in config_map.items() if l!="LOW"},
        "active_games":[{"id":g.id,"level":g.game_level,"status":g.status,"topic_id":g.tg_topic_id,
                         "draw_mode":g.draw_mode,"execution_source":g.execution_source} for g in active],
    }
    print("LOW_READONLY_REPORT="+json.dumps(report,ensure_ascii=False,default=str,sort_keys=True))
    print("PROTECTED_CONFIG_SHA="+digest)
PY
}

echo "===== READ-ONLY BACKEND LOW/FINANCIAL RUNTIME CONFIG ====="
BEFORE="$(backend_audit)" || fail "backend read-only audit failed"
printf '%s\n' "$BEFORE"
GROUP="$(printf '%s\n' "$BEFORE" | sed -n 's/^LOW_READONLY_REPORT=//p' \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["group_id"])')"
LOW_TOPIC="$(printf '%s\n' "$BEFORE" | sed -n 's/^LOW_READONLY_REPORT=//p' \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["game_topics"]["LOW"])')"
BEFORE_SHA="$(printf '%s\n' "$BEFORE" | sed -n 's/^PROTECTED_CONFIG_SHA=//p')"
[[ "$BEFORE_SHA" =~ ^[a-f0-9]{64}$ ]] || fail "invalid protected config fingerprint"

echo "===== READ-ONLY TELEGRAM FORUM, TOPICS, PERMISSIONS AND REDIS KEY ====="
docker exec -i -e EXPECTED_FORUM_GROUP="$GROUP" -e EXPECTED_LOW_TOPIC="$LOW_TOPIC" \
  -e GUIDE_CLAIM_KEY="$KEY" davarna-bot python - <<'PY'
import asyncio,os
from aiogram import Bot
from redis.asyncio import Redis
from bot.config import settings
from bot.services.user_forum_navigation import group_guide_text,topic_link

fields=[
    "USER_TOPIC_ANNOUNCE_ID","USER_TOPIC_GAME_LOW_ID","USER_TOPIC_GAME_MEDIUM_ID",
    "USER_TOPIC_GAME_HIGH_ID","USER_TOPIC_LIVE_NUMBERS_ID","USER_TOPIC_RESULTS_ID",
    "USER_TOPIC_RULES_ID","USER_TOPIC_CHAT_ID",
]
values=[getattr(settings,f) for f in fields]
if not settings.USER_FORUM_CHAT_ID or int(settings.USER_FORUM_CHAT_ID)!=int(os.environ["EXPECTED_FORUM_GROUP"]):
    raise SystemExit("BLOCKER: Bot/Backend user forum chat ID mismatch")
if any(v is None or int(v)<=0 for v in values) or len(set(map(int,values)))!=len(fields):
    raise SystemExit("BLOCKER: Bot user forum topic IDs missing or duplicated")
if int(settings.USER_TOPIC_GAME_LOW_ID)!=int(os.environ["EXPECTED_LOW_TOPIC"]):
    raise SystemExit("BLOCKER: Bot/Backend LOW topic ID mismatch")
urls=[topic_link(v) for v in values]
if any(not u or not u.startswith("https://t.me/c/") for u in urls):
    raise SystemExit("BLOCKER: invalid navigation topic link")
text=group_guide_text()
if len(text)>=4000 or text.count('<a href=')!=len(fields):
    raise SystemExit("BLOCKER: guide content or 8 links invalid")
async def main():
    bot=Bot(settings.TELEGRAM_BOT_TOKEN)
    redis=Redis.from_url(settings.REDIS_URL,decode_responses=True)
    try:
        chat=await bot.get_chat(int(settings.USER_FORUM_CHAT_ID))
        if chat.type!="supergroup" or not bool(getattr(chat,"is_forum",False)):
            raise SystemExit("BLOCKER: target chat is not a Telegram forum supergroup")
        me=await bot.get_me()
        member=await bot.get_chat_member(chat.id,me.id)
        status=str(member.status).lower()
        if "administrator" not in status and "creator" not in status:
            raise SystemExit("BLOCKER: bot is not admin of user forum")
        marker=await redis.get(os.environ["GUIDE_CLAIM_KEY"])
        print("FORUM_CHECK: verified supergroup, bot administrator, 8 unique topics")
        print("FORUM_CHAT_ID:",chat.id)
        print("ANNOUNCEMENT_TOPIC_ID:",int(settings.USER_TOPIC_ANNOUNCE_ID))
        print("CAN_PIN_MESSAGES:",getattr(member,"can_pin_messages",None))
        print("GUIDE_REDIS_MARKER:",marker if marker is not None else "NONE")
        print("GUIDE_PREVIEW_BEGIN")
        print(text)
        print("GUIDE_PREVIEW_END")
        if marker is not None:
            raise SystemExit("BLOCKER: guide already claimed/sent or uncertain; never repost automatically")
    finally:
        await redis.aclose()
        await bot.session.close()
asyncio.run(main())
PY

echo "===== PUBLISH GUIDE ONCE TO USER FORUM ANNOUNCEMENTS ====="
# The exact existing, previously reviewed publisher is from pinned merged source.
# Execute it only inside the already-running Bot container; no image/container change.
git show "$SOURCE:dev/ops/publish-user-forum-guide.py" \
  | docker exec -i davarna-bot python - \
  || fail "guide publish may be uncertain: inspect Redis & Telegram before retrying"

echo "===== POST-PUBLISH READ-ONLY AUTOPILOT/FINANCIAL AUDIT ====="
AFTER="$(backend_audit)" || fail "post-publish read-only Backend audit failed"
printf '%s\n' "$AFTER"
AFTER_SHA="$(printf '%s\n' "$AFTER" | sed -n 's/^PROTECTED_CONFIG_SHA=//p')"
if [[ "$AFTER_SHA" != "$BEFORE_SHA" ]]; then
  echo "WARNING: protected runtime/config fingerprint changed during publication; investigate; do not repost" >&2
  exit 3
fi
echo "===== GUIDE PUBLISHED; LOW READ-ONLY PREPARATION COMPLETE ====="
echo "No game, wallet, deposit, crypto address, card price or Autopilot configuration was changed by this script."
