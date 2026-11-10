#!/usr/bin/env bash
# Release gate for unified owner-managed TON/TRON destinations in Bot + Mini.
# Source-only detached tests: NO prod DB, no container recreation, no Telegram bot.
set -Eeuo pipefail
umask 077
REF="${DAVARNA_OWNER_WALLET_TEST_REF:?Pin exact source SHA}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo "BLOCKED: invalid SHA" >&2; exit 2; }
[[ "${DAVARNA_OWNER_WALLET_TEST_APPROVAL:-}" == "RUN_WALLET_SOURCE_TESTS_ONLY" ]] || {
  echo "BLOCKED: explicit source-test approval missing" >&2; exit 2;
}
ROOT=/opt/davarna-v2
BASE=davarna-backend:superadmin-v11-rbac-7101e5c
ID=sha256:42a77764a254d33f058fb1b606b4a274704975feadce717aa47bb336a3cb9d45
cd "$ROOT"
git cat-file -e "$REF^{commit}"
[[ "$(docker image inspect -f '{{.Id}}' "$BASE")" == "$ID" ]] || {
  echo "BLOCKED: verified offline test image missing" >&2; exit 2;
}
WORK="$(mktemp -d /tmp/davarna-owner-wallet-tests.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
git archive "$REF" -- backend davarna-bot | tar -x -C "$WORK"
echo "===== BACKEND + BOT SYNTAX ====="
docker run --rm --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,size=64m \
  -v "$WORK:/workspace:ro" --entrypoint python "$BASE" -c '
from pathlib import Path
files=list(Path("/workspace/backend").rglob("*.py"))+list(Path("/workspace/davarna-bot").rglob("*.py"))
for path in files:
    compile(path.read_bytes(), str(path), "exec")
print("PASS: source Python syntax",len(files),"files")
'
node --check "$WORK/backend/app/static/mini/app.js"
echo "===== OWNER-MANAGED WALLET ISOLATED HTTP TESTS ====="
for suite in \
    test_owner_crypto_wallet_manager.py \
    test_crypto_production_rotation_gate_isolated.py \
    test_mini_crypto_address_proposals.py \
    test_crypto_destination_version_proto.py; do
    echo "===== $suite ====="
    docker run --rm --network none --read-only --cap-drop ALL \
      --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,size=128m \
      --memory=512m --memory-swap=512m \
      -e DATABASE_URL=sqlite+pysqlite:// \
      -e REDIS_URL=redis://127.0.0.1:6379/15 \
      -e CRYPTO_PAYMENTS_ENABLED=false \
      -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
      -e DAVARNA_CRYPTO_ROTATION_PRODUCTION= \
      -e DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL= \
      -e GAME_AUTO_DRAW_ENABLED=false \
      -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
      -e RECEIPTS_DIR=/tmp/receipts \
      -v "$WORK/backend:/app:ro" -w /app \
      --entrypoint python "$BASE" -m unittest discover -s tests -p "$suite" -v
done
echo "===== OWNER CRYPTO WALLET BOT+MINI SOURCE GATE PASS ====="
echo "SOURCE=$REF"
echo "PRODUCTION_UNCHANGED=true"
echo "NO_REAL_FUNDS=true"
