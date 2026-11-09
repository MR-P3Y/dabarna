#!/usr/bin/env bash
# Davarna v1.0 release-candidate verification — READ ONLY.
# No deploy, compose up, DB migrations, Telegram messages or wallet writes.
set -Eeuo pipefail
umask 077

cd /opt/davarna-v2
BRANCH="release/v1.0-rc-20261109"
REF="$DAVARNA_V1_RC_REF"
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || { echo "BLOCK: SHA is not pinned"; exit 2; }
test "$(git rev-parse "origin/$BRANCH")" = "$REF" || {
  echo "BLOCK: release candidate branch changed"; exit 2;
}

WORK=$(mktemp -d /tmp/davarna-v1-rc.XXXXXX)
trap 'rm -rf -- "$WORK"' EXIT

git archive "$REF" -- \
  davarna-bot \
  backend/app/utils/bingo_v2.py \
  backend/app/routers/mini_router.py \
  backend/app/static/mini/app.js \
  backend/app/static/mini/index.html \
  backend/tests/test_bingo_v2.py \
  backend/tests/test_game_forum_lifecycle_contract.py \
  | tar -x -C "$WORK"

export PYTHONDONTWRITEBYTECODE=1

echo "===== 1/4 BOT DELIVERY / RESTART ====="
PYTHONPATH="$WORK/davarna-bot" python3 -B -m unittest discover \
  -s "$WORK/davarna-bot/tests" \
  -p test_lifecycle_delivery_ack.py -v

echo "===== 2/4 GAME RULES / TELEGRAM CONTRACT ====="
python3 -B -m unittest discover \
  -s "$WORK/backend/tests" \
  -p test_game_forum_lifecycle_contract.py -v

echo "===== 3/4 V2 CARD AND WIN DETECTION ====="
PYTHONPATH="$WORK/backend" python3 -B -m unittest discover \
  -s "$WORK/backend/tests" \
  -p test_bingo_v2.py -v

echo "===== 4/4 SYNTAX / SERVER HEALTH SNAPSHOT ====="
python3 -B -m py_compile \
  "$WORK/davarna-bot/bot/workers/notifier.py" \
  "$WORK/davarna-bot/bot/services/lifecycle_delivery.py" \
  "$WORK/davarna-bot/bot/services/notify_store.py" \
  "$WORK/davarna-bot/bot/services/user_topics.py" \
  "$WORK/davarna-bot/bot/services/user_forum_navigation.py" \
  "$WORK/backend/app/routers/mini_router.py"

if command -v node >/dev/null 2>&1; then
  node --check "$WORK/backend/app/static/mini/app.js"
else
  echo "NOT TESTED: node unavailable for Mini JavaScript syntax"
fi

echo "--- Running Davarna containers (read-only) ---"
docker ps --format '{{.Names}}  {{.Status}}  {{.Image}}' |
  grep -E '^davarna-' || echo "WARN: no running davarna-* container"
echo "--- Host capacity ---"
df -h /opt/davarna-v2 | tail -n 1
free -h | sed -n '1,3p'
echo "===== V1.0 RC OFFLINE GATE PASS ====="
