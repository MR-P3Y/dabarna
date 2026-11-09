#!/usr/bin/env bash
# Final isolated gate for #30 preview/draft/review workflow and historical queue.
# NEVER deploys, merges, alters Production DB, rotates addresses or credits wallets.
set -Eeuo pipefail
umask 077
cd /opt/davarna-v2

BRANCH="feature/roadmap-crypto-rules-ui-20261108"
SOURCE="${DAVARNA_CRYPTO_FINAL_REF:-}"
[[ "$SOURCE" =~ ^[0-9a-f]{40}$ ]] || { echo "BLOCKER: pinned source SHA required"; exit 2; }
[[ "$(git rev-parse "origin/$BRANCH")" == "$SOURCE" ]] || {
  echo "BLOCKER: branch SHA drift"; exit 2;
}
IMAGE="davarna-backend:finance-pr31-90f6670"
WORK="$(mktemp -d /tmp/davarna-crypto30-final.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
git archive "$SOURCE" -- backend davarna-bot \
  dev/release/test-crypto-late-queue-mysql-20261109.sh |
  tar -x -C "$WORK"

echo "===== NO-NETWORK UNIT AND UI CONTRACTS ====="
for pattern in \
  test_crypto_late_payment_queue.py \
  test_crypto_destination_drafts.py \
  test_crypto_destination_confirmations.py \
  test_crypto_rotation_ui_contract.py
do
  echo "===== $pattern ====="
  docker run --rm --network none --read-only \
    --memory 512m --cpus 1 --pids-limit 128 \
    --cap-drop ALL --security-opt no-new-privileges \
    --tmpfs /tmp:rw,nosuid,nodev \
    -e DATABASE_URL=sqlite+pysqlite:///:memory: \
    -e REDIS_URL=redis://127.0.0.1:6379/0 \
    -e RECEIPTS_DIR=/tmp/receipts \
    -e PYTHONPATH=/work/backend -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$WORK:/work:ro" -w /work/backend \
    --entrypoint python "$IMAGE" \
    -m unittest discover -s tests -p "$pattern" -v
done

echo "===== MINI JS SYNTAX ====="
if command -v node >/dev/null 2>&1; then
  node --check "$WORK/backend/app/static/mini/app.js"
  echo "PASS: mini app JavaScript syntax"
else
  echo "WARNING: node is unavailable on host; JavaScript syntax not checked"
fi

echo "===== RESTRICTED MYSQL QUEUE / AUDIT INTEGRATION ====="
bash -n "$WORK/dev/release/test-crypto-late-queue-mysql-20261109.sh"
DAVARNA_CRYPTO_QUEUE_TEST_APPROVAL=ISOLATED_SCHEMA_ONLY \
DAVARNA_CRYPTO_QUEUE_TEST_SOURCE_SHA="$SOURCE" \
  bash "$WORK/dev/release/test-crypto-late-queue-mysql-20261109.sh"

echo "===== #30 FINAL ISOLATED GATE COMPLETE ====="
