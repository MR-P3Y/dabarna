#!/usr/bin/env bash
# One final offline gate for Telegram lifecycle delivery ACK fix.
# Read-only source; NO Bot/Telegram calls, Production DB changes or restarts.
set -Eeuo pipefail
umask 077
cd /opt/davarna-v2

BRANCH="fix/telegram-lifecycle-delivery-ack-20261109"
REF="$DAVARNA_TELEGRAM_ACK_REF"
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || { echo "BLOCKER: pinned SHA required"; exit 2; }
[[ "$(git rev-parse "origin/$BRANCH")" == "$REF" ]] || {
  echo "BLOCKER: branch changed"; exit 2;
}
WORK="$(mktemp -d /tmp/davarna-telegram-ack.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
git archive "$REF" -- davarna-bot backend/app/routers/mini_router.py \
    backend/tests/test_game_forum_lifecycle_contract.py |
  tar -x -C "$WORK"

echo "===== LIFECYCLE ACK / RESTART OFFLINE TESTS ====="
PYTHONPATH="$WORK/davarna-bot" \
  python3 -m unittest discover \
    -s "$WORK/davarna-bot/tests" \
    -p test_lifecycle_delivery_ack.py -v

echo "===== EXISTING TELEGRAM GAME-RULE CONTRACTS ====="
python3 -m unittest discover \
  -s "$WORK/backend/tests" \
  -p test_game_forum_lifecycle_contract.py -v

echo "===== PYTHON SYNTAX ====="
python3 -m py_compile \
  "$WORK/davarna-bot/bot/workers/notifier.py" \
  "$WORK/davarna-bot/bot/services/notify_store.py" \
  "$WORK/davarna-bot/bot/services/lifecycle_delivery.py" \
  "$WORK/davarna-bot/bot/services/user_topics.py" \
  "$WORK/backend/app/routers/mini_router.py"

echo "===== TELEGRAM LIFECYCLE ACK OFFLINE GATE COMPLETE ====="
