#!/usr/bin/env bash
# V1.2 isolated test harness. NEVER uses production database, networks or volumes.
set -Eeuo pipefail
umask 077
ROOT=/opt/davarna-v2
IMAGE=davarna-backend:superadmin-v11-rbac-7101e5c
EXPECTED=sha256:42a77764a254d33f058fb1b606b4a274704975feadce717aa47bb336a3cb9d45
REF="${DAVARNA_V12_TEST_REF:?Set verified V1.2 commit SHA}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo "BLOCKER: invalid test ref" >&2; exit 2; }
cd "$ROOT"
git cat-file -e "$REF^{commit}" || { echo "BLOCKER: ref unavailable" >&2; exit 2; }
[[ "$(docker image inspect -f '{{.Id}}' "$IMAGE")" == "$EXPECTED" ]] || {
  echo "BLOCKER: local backend test dependency image changed" >&2; exit 2;
}
WORK=$(mktemp -d /tmp/davarna-v12-test.XXXXXX)
trap 'rm -rf -- "$WORK"' EXIT
echo "===== ARCHIVE PINNED SOURCE ====="
git archive "$REF" -- backend | tar -x -C "$WORK"
echo "===== NODE SYNTAX ====="
node --check "$WORK/backend/app/static/mini/app.js"
echo "===== NODE V1.2 CONTRACT ====="
node "$WORK/backend/tests/js/test_superadmin_dashboard_v11.mjs"
echo "===== PYTHON ISOLATED HTTP/RBAC + CRYPTO PROPOSAL TESTS ====="
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,size=128m \
  -e DATABASE_URL=sqlite+pysqlite:///:memory: \
  -e REDIS_URL=redis://127.0.0.1:6379/15 \
  -e RECEIPTS_DIR=/tmp/receipts \
  -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
  -e GAME_AUTO_DRAW_ENABLED=false \
  -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
  -v "$WORK/backend:/app:ro" -w /app \
  --entrypoint python "$IMAGE" \
  -m unittest discover -s tests -p 'test_mini_crypto_address_proposals.py' -v

docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,size=128m \
  -e DATABASE_URL=sqlite+pysqlite:///:memory: \
  -e REDIS_URL=redis://127.0.0.1:6379/15 \
  -e RECEIPTS_DIR=/tmp/receipts \
  -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
  -e GAME_AUTO_DRAW_ENABLED=false \
  -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
  -v "$WORK/backend:/app:ro" -w /app \
  --entrypoint python "$IMAGE" \
  -m unittest discover -s tests -p 'test_mini_ops_dashboard_rbac_http.py' -v
echo "===== CRYPTO DESTINATION MATCH ISOLATION ====="
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,size=128m \
  -e DATABASE_URL=sqlite+pysqlite:///:memory: \
  -e REDIS_URL=redis://127.0.0.1:6379/15 \
  -e RECEIPTS_DIR=/tmp/receipts \
  -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
  -e GAME_AUTO_DRAW_ENABLED=false \
  -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
  -v "$WORK/backend:/app:ro" -w /app \
  --entrypoint python "$IMAGE" \
  -m unittest discover -s tests -p 'test_crypto_destination_match_isolated.py' -v
echo "===== MULTI-ADDRESS WORKER ISOLATION ====="
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,size=128m \
  -e DATABASE_URL=sqlite+pysqlite:///:memory: \
  -e REDIS_URL=redis://127.0.0.1:6379/15 \
  -e RECEIPTS_DIR=/tmp/receipts \
  -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
  -e GAME_AUTO_DRAW_ENABLED=false \
  -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
  -v "$WORK/backend:/app:ro" -w /app \
  --entrypoint python "$IMAGE" \
  -m unittest discover -s tests -p 'test_crypto_multi_address_worker_isolated.py' -v
echo "===== PROVIDER CONTRACT MOCKS ====="
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,size=128m \
  -e DATABASE_URL=sqlite+pysqlite:///:memory: \
  -e REDIS_URL=redis://127.0.0.1:6379/15 \
  -e RECEIPTS_DIR=/tmp/receipts \
  -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
  -e GAME_AUTO_DRAW_ENABLED=false \
  -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
  -v "$WORK/backend:/app:ro" -w /app \
  --entrypoint python "$IMAGE" \
  -m unittest discover -s tests -p 'test_crypto_multi_address_provider_contracts.py' -v
for suite in test_crypto_scan_pagination_isolated.py test_crypto_late_transfer_inbox_isolated.py; do
  echo "===== CRYPTO SAFETY SUITE: $suite ====="
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,size=128m \
    -e DATABASE_URL=sqlite+pysqlite:///:memory: \
    -e REDIS_URL=redis://127.0.0.1:6379/15 \
    -e RECEIPTS_DIR=/tmp/receipts \
    -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
    -e GAME_AUTO_DRAW_ENABLED=false \
    -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
    -v "$WORK/backend:/app:ro" -w /app \
    --entrypoint python "$IMAGE" \
    -m unittest discover -s tests -p "$suite" -v
done
echo "===== ROTATION READINESS AND EXPIRY ISOLATION ====="
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,size=128m \
  -e DATABASE_URL=sqlite+pysqlite:///:memory: \
  -e REDIS_URL=redis://127.0.0.1:6379/15 \
  -e RECEIPTS_DIR=/tmp/receipts \
  -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
  -e GAME_AUTO_DRAW_ENABLED=false \
  -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
  -v "$WORK/backend:/app:ro" -w /app \
  --entrypoint python "$IMAGE" \
  -m unittest discover -s tests -p 'test_crypto_rotation_readiness_isolated.py' -v
echo "===== WALLET VERSIONING PROTOTYPE (SERIAL SQLITE) ====="
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,size=128m \
  -e DATABASE_URL=sqlite+pysqlite:///:memory: \
  -e REDIS_URL=redis://127.0.0.1:6379/15 \
  -e RECEIPTS_DIR=/tmp/receipts \
  -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
  -e GAME_AUTO_DRAW_ENABLED=false \
  -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
  -v "$WORK/backend:/app:ro" -w /app \
  --entrypoint python "$IMAGE" \
  -m unittest discover -s tests -p 'test_crypto_destination_version_proto.py' -v
echo "===== CLOSED INVOICE AND REPLAY GUARDS ====="
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,size=128m \
  -e DATABASE_URL=sqlite+pysqlite:///:memory: \
  -e REDIS_URL=redis://127.0.0.1:6379/15 \
  -e RECEIPTS_DIR=/tmp/receipts \
  -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
  -e GAME_AUTO_DRAW_ENABLED=false \
  -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
  -v "$WORK/backend:/app:ro" -w /app \
  --entrypoint python "$IMAGE" \
  -m unittest discover -s tests -p 'test_crypto_late_replay_guard_isolated.py' -v
echo "===== V1.2 ISOLATED TEST PASS ====="
