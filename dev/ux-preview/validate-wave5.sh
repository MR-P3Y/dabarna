#!/usr/bin/env bash
# Wave-5 static + isolated regression gates. Never deploys or restarts services.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

EXPECTED_BRANCH="feature/ui-ux-refresh-tambola-v2-20261106"
CURRENT_BRANCH="$(git branch --show-current)"
if [[ "$CURRENT_BRANCH" != "$EXPECTED_BRANCH" ]]; then
  echo "STOP: expected branch $EXPECTED_BRANCH, found $CURRENT_BRANCH" >&2
  exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "STOP: working tree contains uncommitted tracked changes." >&2
  exit 1
fi

BACKEND_IMAGE="davarna-backend:v2-937ef711a9db"
BOT_IMAGE="davarna-bot:v2-937ef711a9db"
for image in node:22-alpine "$BACKEND_IMAGE" "$BOT_IMAGE"; do
  docker image inspect "$image" >/dev/null || {
    echo "STOP: missing local image $image" >&2
    exit 1
  }
done

echo "===== JS SYNTAX AND NODE UX REGRESSIONS ====="
docker run --rm --network none \
  -v "$ROOT/backend:/qa/backend:ro" \
  -v "$ROOT/dev/ux-preview:/qa/dev/ux-preview:ro" \
  -w /qa \
  --entrypoint sh node:22-alpine -ec '
    set -e
    node --check backend/app/static/mini/app.js
    for test in \
      test_game_discovery_ux.mjs \
      test_admin_navigation_ux.mjs \
      test_notification_rule_labels.mjs \
      test_navigation_regressions_wave5.mjs \
      test_ux_preview_safety.mjs; do
        echo "----- $test -----"
        node "backend/tests/js/$test"
    done
  '

echo "===== ISOLATED BACKEND UX CONTRACT TESTS ====="
for test in \
  test_mini_navigation_ux.py \
  test_mini_wallet_rule_metadata.py \
  test_bot_wallet_rule_metadata.py; do
  echo "----- $test -----"
  docker run --rm --network none \
    -v "$ROOT/backend:/app:ro" -w /app \
    "$BACKEND_IMAGE" \
    python -m unittest discover -s tests -p "$test" -v
done

echo "===== ISOLATED TELEGRAM BOT TESTS ====="
for test in \
  test_winner_archive_ux_v2.py \
  test_help_v2_rules.py \
  test_notification_rule_consistency.py; do
  echo "----- $test -----"
  docker run --rm --network none \
    -e TELEGRAM_BOT_TOKEN=123456789:TEST_ONLY \
    -v "$ROOT/davarna-bot/bot:/app/bot:ro" \
    -v "$ROOT/davarna-bot/tests:/app/tests:ro" \
    -w /app "$BOT_IMAGE" \
    python -m unittest discover -s tests -p "$test" -v
done

echo "===== WAVE 5 REGRESSION GATES PASSED ====="
