#!/usr/bin/env bash
# Build matched NON-DEPLOYED owner-wallet Backend(V1.3 Mini) + Telegram Bot.
# No DB access, no Bot polling, no live compose, no live volumes, no published ports.
set -Eeuo pipefail
umask 077

ROOT=/opt/davarna-v2
REF="${DAVARNA_OWNER_WALLET_BUILD_REF:?Set the exact tested source SHA}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo "BLOCKED: invalid source SHA" >&2; exit 2; }
[[ "${DAVARNA_OWNER_WALLET_BUILD_APPROVAL:-}" == "BUILD_BOT_MINI_NONDEPLOYED_ONLY" ]] || {
  echo "BLOCKED: build-only approval missing" >&2; exit 2;
}
cd "$ROOT"
git cat-file -e "$REF^{commit}"

BACKEND_TAG="davarna-backend:owner-wallet-v13-${REF:0:12}"
BOT_TAG="davarna-bot:owner-wallet-${REF:0:12}"
BUILDER="$(mktemp /tmp/davarna-owner-wallet-builder.XXXXXX.sh)"
WORK="$(mktemp -d /tmp/davarna-owner-wallet-bot.XXXXXX)"
trap 'rm -f -- "$BUILDER"; rm -rf -- "$WORK"' EXIT

# Both images are pinned to the same source commit.
echo "===== BUILD MATCHED SUPERADMIN V1.3 + OWNER-WALLET BACKEND ====="
git show "$REF:dev/release/build-zero-km-v12-v13-candidate-20261110.sh" > "$BUILDER"
bash -n "$BUILDER"
DAVARNA_ZERO_KM_COMBINED_REF="$REF" \
DAVARNA_ZERO_KM_BUILD_APPROVAL=BUILD_NONDEPLOYED_CANDIDATE_ONLY \
  bash "$BUILDER"

BUILD_TAG="davarna-backend:zero-km-combined-${REF:0:12}"
docker image inspect "$BUILD_TAG" >/dev/null
docker tag "$BUILD_TAG" "$BACKEND_TAG"

echo "===== CHECK ACTUAL MINI + API CONTRACT INSIDE BACKEND IMAGE ====="
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --entrypoint python "$BACKEND_TAG" -c '
from pathlib import Path
index = Path("/app/app/static/mini/index.html").read_text()
js = Path("/app/app/static/mini/app.js").read_text()
mini = Path("/app/app/routers/mini_router.py").read_text()
bot_api = Path("/app/app/routers/bot_router.py").read_text()
crypto = Path("/app/app/services/crypto_deposit_service.py").read_text()
checks = {
 "Superadmin V1.3 layout": "superadmin-workspace-v13" in index,
 "Mini add/edit controls": "افزودن یا تغییر آدرس دریافت" in index,
 "Mini first add endpoint wiring": "/mini-api/admin/super/crypto-address-initialize-production" in js,
 "Mini final activate wiring": "/mini-api/admin/super/crypto-address-activate-production" in js,
 "Backend first-add endpoint": "def mini_super_crypto_address_initialize_production" in mini,
 "Backend bot owner endpoint": "def bot_owner_crypto_wallet_activate" in bot_api,
 "Versioned DB destination": "lock_destination_state_from_record" in crypto,
}
for name, ok in checks.items():
 print(("PASS" if ok else "FAIL") + ": " + name)
assert all(checks.values()), "Incomplete wallet manager image"
'

echo "===== BUILD NONDEPLOYED TELEGRAM BOT OVER VERIFIED RUNNING BOT BASE ====="
BOT_BASE="$(docker inspect -f '{{.Config.Image}}' davarna-bot)"
BOT_BASE_ID="$(docker inspect -f '{{.Image}}' davarna-bot)"
[[ "$(docker image inspect -f '{{.Id}}' "$BOT_BASE")" == "$BOT_BASE_ID" ]] || {
  echo "BLOCKED: running Bot image differs from local tag" >&2; exit 3;
}
git archive "$REF" -- davarna-bot | tar -x -C "$WORK"
mkdir -p "$WORK/build"
cp -a "$WORK/davarna-bot/bot" "$WORK/build/"
# Using already-installed Bot dependencies avoids apt/pip calls and
# guarantees no second live Bot is created or started.
cat > "$WORK/build/Dockerfile" <<'DOCKER'
ARG BASE
FROM ${BASE}
COPY bot/ /app/bot/
DOCKER
docker build --pull=false --network none \
  -f "$WORK/build/Dockerfile" \
  --build-arg "BASE=$BOT_BASE" \
  --tag "$BOT_TAG" "$WORK/build"

echo "===== VERIFY BOT SOURCE CHECKSUMS ====="
for file in \
  bot/routers/super_admin.py \
  bot/keyboards/super_admin.py \
  bot/states/super_admin.py \
  bot/services/api_client.py; do
  wanted="$(sha256sum "$WORK/davarna-bot/$file" | awk '{print $1}')"
  actual="$(docker run --rm --network none --read-only --entrypoint sha256sum "$BOT_TAG" "/app/$file" | awk '{print $1}')"
  [[ "$wanted" == "$actual" ]] || { echo "BLOCKED: bot file mismatch $file" >&2; exit 4; }
  echo "PASS: $file"
done

echo "===== CHECK NO PRODUCTION IMAGE SWAP OCCURRED ====="
[[ "$(docker inspect -f '{{.Image}}' davarna-bot)" == "$BOT_BASE_ID" ]] || {
  echo "BLOCKED: live bot unexpectedly changed" >&2; exit 5;
}
for service in davarna-backend davarna-bot davarna-mysql; do
  [[ "$(docker inspect -f '{{.State.Running}}' "$service")" == true ]] || {
    echo "BLOCKED: production service not running: $service" >&2; exit 5;
  }
done
echo "===== OWNER WALLET BOT + MINI V1.3 MATCHED CANDIDATES READY ====="
echo "SOURCE=$REF"
echo "BACKEND_IMAGE=$BACKEND_TAG"
docker image inspect -f 'BACKEND_IMAGE_ID={{.Id}}' "$BACKEND_TAG"
echo "BOT_IMAGE=$BOT_TAG"
docker image inspect -f 'BOT_IMAGE_ID={{.Id}}' "$BOT_TAG"
echo "PRODUCTION_CHANGED=false"
echo "BOT_STARTED=false"
echo "CRYPTO_ADDRESSES_CHANGED=false"
echo "NEXT=private staging verification, NOT live finance activation"
