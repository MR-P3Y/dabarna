#!/usr/bin/env bash
# Davarna v1.0 release-candidate OFFLINE gate only.
# No Production deployment, database write, Telegram send, or Docker restart.
set -Eeuo pipefail
umask 077

cd /opt/davarna-v2
BRANCH="release/davarna-v1-candidate-20261109"
REF="$(printenv DAVARNA_V1_REF || true)"
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || { echo "BLOCKER: full pinned SHA required"; exit 2; }
[[ "$(git rev-parse "origin/$BRANCH")" == "$REF" ]] || {
  echo "BLOCKER: candidate branch SHA changed"; exit 2;
}

WORK="$(mktemp -d /tmp/davarna-v1-gate.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
git archive "$REF" -- backend davarna-bot | tar -x -C "$WORK"

echo "===== v1 BINGO V2 CARD RULES ====="
PYTHONPATH="$WORK/backend" python3 -m unittest discover \
  -s "$WORK/backend/tests" -p 'test_bingo_v2.py' -v

echo "===== v1 TELEGRAM DELIVERY + RESTART ====="
PYTHONPATH="$WORK/davarna-bot" python3 -m unittest discover \
  -s "$WORK/davarna-bot/tests" -p 'test_lifecycle_delivery_ack.py' -v

echo "===== v1 FORUM RULE + TOPIC CONTRACTS ====="
python3 -m unittest discover \
  -s "$WORK/backend/tests" -p 'test_game_forum_lifecycle_contract.py' -v

echo "===== v1 BACKEND/MINI RULE LABELS (NO NETWORK) ====="
IMAGE="$(printenv DAVARNA_V1_TEST_IMAGE || true)"
if [[ -z "$IMAGE" ]]; then IMAGE="davarna-backend:finance-pr31-90f6670"; fi
docker image inspect "$IMAGE" >/dev/null 2>&1 || {
  echo "BLOCKER: local backend test image unavailable: $IMAGE"; exit 2;
}
docker run --rm --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m \
  --mount "type=bind,source=$WORK/backend,target=/work/backend,readonly" \
  --workdir /work/backend \
  --env PYTHONPATH=/work/backend \
  --env PYTHONDONTWRITEBYTECODE=1 \
  "$IMAGE" python -m unittest discover \
  -s /work/backend/tests -p 'test_mini_game_rule_labels.py' -v

echo "===== v1 SYNTAX ====="
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  "$WORK/backend/app/services/game_service.py" \
  "$WORK/backend/app/services/game_autopilot_worker.py" \
  "$WORK/backend/app/routers/mini_router.py" \
  "$WORK/davarna-bot/bot/workers/notifier.py" \
  "$WORK/davarna-bot/bot/services/lifecycle_delivery.py" \
  "$WORK/davarna-bot/bot/services/notify_store.py"
if command -v node >/dev/null 2>&1; then
  node --check "$WORK/backend/app/static/mini/app.js"
  echo "PASS: mini JS syntax"
else
  echo "NOT TESTED: Node.js not installed; mini JS syntax check skipped"
fi

echo "===== v1 OFFLINE RELEASE-CANDIDATE GATE COMPLETE ====="
