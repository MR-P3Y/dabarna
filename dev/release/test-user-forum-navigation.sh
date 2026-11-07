#!/usr/bin/env bash
# Offline regression suite for group UX changes. Does not contact Telegram,
# modify production databases, recreate containers, or change runtime flags.
set -Eeuo pipefail
umask 077
cd /opt/davarna-v2
BRANCH=feature/forum-navigation-20261107
BOT_IMAGE=davarna-bot:pr13-d9434cb10d71
BACK_IMAGE=davarna-backend:rbac-pr14-e087c40bd471

[[ "$(id -u)" == 0 ]] || { echo "BLOCKER: root required"; exit 2; }
git rev-parse --verify "origin/$BRANCH" >/dev/null
docker image inspect "$BOT_IMAGE" >/dev/null
docker image inspect "$BACK_IMAGE" >/dev/null

WORK="$(mktemp -d /tmp/davarna-user-forum-XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
chmod 0700 "$WORK"
git archive "origin/$BRANCH" -- davarna-bot backend/app/routers/mini_router.py \
  backend/tests/test_user_forum_created_notice.py | tar -x -C "$WORK"

echo "===== BOT OFFLINE REGRESSION SUITE ====="
docker run --rm --network none --read-only --memory 512m --cpus 1 \
  --tmpfs /tmp:rw,nosuid,nodev --security-opt no-new-privileges \
  --entrypoint python -e TELEGRAM_BOT_TOKEN='123456789:TEST_ONLY' \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$WORK/davarna-bot:/app:ro" -w /app "$BOT_IMAGE" \
  -m unittest discover -s tests -p 'test_*.py' -v

echo "===== BACKEND PUBLIC ANNOUNCEMENT REGRESSION ====="
docker run --rm --network none --read-only --memory 384m --cpus 1 \
  --tmpfs /tmp:rw,nosuid,nodev --security-opt no-new-privileges \
  --entrypoint python -e RECEIPTS_DIR=/tmp/receipts \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$WORK/backend:/app:ro" -w /app "$BACK_IMAGE" \
  -m unittest discover -s tests -p test_user_forum_created_notice.py -v

echo "===== ALL FORUM NAVIGATION REGRESSIONS PASSED ====="
