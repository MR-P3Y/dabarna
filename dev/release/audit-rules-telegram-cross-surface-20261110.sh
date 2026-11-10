#!/usr/bin/env bash
# Read-only NODE2 release gate for #25/#27/#29/#33/#34.
# Tests candidate in isolated no-network containers; never sends Telegram messages
# and never alters production games, wallets, settings or bot ACKs.
set -Eeuo pipefail
umask 077
die(){ echo "BLOCKER: $*" >&2; exit 2; }
ROOT=/opt/davarna-v2
REF="${DAVARNA_RULES_TELEGRAM_AUDIT_REF:?pinned ref required}"
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || die "invalid SHA"
cd "$ROOT"
git cat-file -e "$REF^{commit}" || die "commit not fetched"
[[ "$(id -u)" == 0 ]] || die "root required"
exec 9>/run/davarna-rules-telegram-audit.lock
flock -n 9 || die "another rules/Telegram audit in progress"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
 [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || die "unhealthy: $c"
done
WORK="$(mktemp -d /tmp/davarna-rules-telegram-gate.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
git archive "$REF" backend davarna-bot | tar -xf - -C "$WORK"
echo "===== PINNED SOURCE AND LIVE IMAGE INVENTORY ====="
echo "SOURCE=$REF"
docker inspect -f 'BACKEND_IMAGE={{.Config.Image}} IMAGE_ID={{.Image}}' davarna-backend
docker inspect -f 'BOT_IMAGE={{.Config.Image}} IMAGE_ID={{.Image}}' davarna-bot
echo "===== SOURCE RULES AND ROUTING TESTS (OFFLINE BACKEND) ====="
BACKEND_IMAGE="$(docker inspect -f '{{.Config.Image}}' davarna-backend)"
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
 --tmpfs /tmp:rw,nosuid,size=128m \
 -v "$WORK:/src:ro" -w /src/backend --entrypoint python \
 -e DATABASE_URL=sqlite+pysqlite:///:memory: \
 -e REDIS_URL=redis://127.0.0.1:6379/14 \
 -e TELEGRAM_BOT_TOKEN=123456789:ISOLATED_TEST_ONLY \
 -e PYTHONPATH=/src/backend \
 "$BACKEND_IMAGE" -c 'import sys,unittest
loader=unittest.TestLoader()
suite=unittest.TestSuite(loader.discover("tests",pattern=name) for name in sys.argv[1:])
result=unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)' \
 test_bingo_v2.py test_game_v2_dispatch.py test_mini_game_rule_labels.py \
 test_mini_wallet_rule_metadata.py test_bot_wallet_rule_metadata.py \
 test_game_forum_lifecycle_contract.py test_user_forum_created_notice.py
echo "===== TELEGRAM RETRY / RULES / FORUM TESTS (OFFLINE BOT) ====="
BOT_IMAGE="$(docker inspect -f '{{.Config.Image}}' davarna-bot)"
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
 --tmpfs /tmp:rw,nosuid,size=128m \
 -v "$WORK:/src:ro" -w /src/davarna-bot --entrypoint python \
 -e TELEGRAM_BOT_TOKEN=123456789:ISOLATED_TEST_ONLY \
 -e API_BASE_URL=http://127.0.0.1:9 \
 -e PYTHONPATH=/src/davarna-bot \
 "$BOT_IMAGE" -c 'import sys,unittest
loader=unittest.TestLoader()
suite=unittest.TestSuite(loader.discover("tests",pattern=name) for name in sys.argv[1:])
result=unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)' \
 test_card_layout_v2.py test_help_v2_rules.py test_notification_rule_consistency.py \
 test_public_forum_notices.py test_lifecycle_delivery_ack.py
echo "===== MINI APP LABEL TEST (OFFLINE NODE) ====="
if command -v node >/dev/null 2>&1;then
 (cd "$WORK/backend" && node tests/js/test_notification_rule_labels.mjs)
else
 echo "BLOCKER: Node.js unavailable on host; JS contract cannot be verified"
 exit 2
fi
echo "===== LIVE GAME RULE CONTRACTS (READ-ONLY) ====="
docker exec -i davarna-backend python - <<'PY'
from sqlalchemy import select,func
from app.core.db import SessionLocal
from app.models.game import Game,GameCard
from app.models.game_event import GameEvent
expected={88:("LOW","LINE",2),90:("MEDIUM","LINE",2),93:("HIGH","FULL_CARD",2)}
with SessionLocal() as db:
 for gid,(level,rule,layout) in expected.items():
  g=db.get(Game,gid)
  assert g and str(g.status)=="ENDED",f"missing settled game {gid}"
  assert (str(g.game_level),str(g.game_rule),int(g.card_layout_version))==(level,rule,layout),f"rule drift game {gid}"
  cards=db.execute(select(GameCard.numbers_json).where(GameCard.game_id==gid)).scalars().all()
  assert cards,f"missing cards for game {gid}"
  for raw in cards:
   values=raw.get("numbers") if isinstance(raw,dict) else raw
   assert isinstance(values,list) and len(values)==27,f"invalid v2 layout game {gid}"
   assert len([v for v in values if int(v)>0])==15,f"invalid number count game {gid}"
  ev=db.execute(select(GameEvent.kind,func.count(GameEvent.id)).where(GameEvent.game_id==gid).group_by(GameEvent.kind)).all()
  counts=dict(ev)
  assert counts.get("GAME_CREATED",0)==1 and counts.get("GAME_STARTED",0)==1 and counts.get("GAME_ENDED",0)==1,f"event count drift game {gid}"
  print(f"PASS LIVE RULE: #{gid} level={level} rule={rule} cards={len(cards)} created/started/ended=1/1/1")
print("PASS: LIVE GAME RULE CONTRACTS")
PY
echo "===== PRODUCTION BOT DELIVERY-ACK INVENTORY (READ ONLY) ====="
docker exec -i davarna-bot python - <<'PY'
from pathlib import Path
import hashlib
import json
from bot.services import notify_store
from bot.services.user_topics import game_start_announcement_topic
from bot.config import settings
from bot.workers import notifier
print("BOT_START_TOPIC_CONFIGURED:",settings.USER_TOPIC_GAME_START_ID is not None)
print("BOT_START_ROUTE:",game_start_announcement_topic())
p=Path(notifier.__file__)
print("BOT_NOTIFIER_SHA256:",hashlib.sha256(p.read_bytes()).hexdigest())
print("BOT_NOTIFIER_PATH:",str(p))
state=Path("storage/notif_state.json")
print("BOT_ACK_STORE_PRESENT:",state.is_file())
if state.is_file():
 data=json.loads(state.read_text(encoding="utf-8"))
 for gid in (88,90,93):
  entry=(data.get("events") or {}).get(str(gid),{})
  keys=["GAME_CREATED_NOTICE_USER","GAME_STARTED_NOTICE_ADMIN","GAME_STARTED_NOTICE_USER","GAME_ENDED_NOTICE_ADMIN","GAME_ENDED_NOTICE_USER"]
  relevant={key:int(entry.get(key,0) or 0) for key in keys}
  print("GAME",gid,"ACK_MARKERS",relevant)
  legacy={key:int(entry.get(key,0) or 0) for key in ("GAME_CREATED_NOTICE","GAME_STARTED_NOTICE","GAME_ENDED_NOTICE")}
  print("GAME",gid,"LEGACY_MARKERS",legacy)
else:
 print("INFO: inspect bot notification storage mount; no ACK inference")
PY
echo "===== DEPLOYED-VS-GITHUB TELEGRAM CODE PROVENANCE ====="
# Hash actual files without exporting tokens, .env, state, or copy of the Bot filesystem.
for path in bot/workers/notifier.py bot/services/lifecycle_delivery.py bot/services/user_topics.py; do
 candidate="$WORK/davarna-bot/$path"
 expected="$(sha256sum "$candidate" | cut -d' ' -f1)"
 live="$(docker exec -i davarna-bot python - "$path" <<'PY'
import hashlib
from pathlib import Path
import sys
from bot.workers import notifier
base=Path(notifier.__file__).resolve().parents[1]
relative=Path(sys.argv[1])
target=base.parent / relative
if target.is_file():
 print(hashlib.sha256(target.read_bytes()).hexdigest())
else:
 print("MISSING")
PY
)"
 if [[ "$expected" == "$live" ]];then
  echo "SOURCE_MATCH $path PASS"
 else
  echo "SOURCE_MATCH $path NOT_DEPLOYED_OR_MODIFIED"
 fi
done
echo "===== RULES / TELEGRAM AUDIT COMPLETE ====="
echo "No live Telegram sends or changes to Production data or containers."
