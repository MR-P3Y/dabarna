#!/usr/bin/env bash
# Compare release image bytes against an exact source commit. READ ONLY.
# Use after a candidate image was built, before attempting a deployment.
set -Eeuo pipefail
REF="${DAVARNA_WALLET_RELEASE_IMAGE_REF:?Pin immutable Git SHA}"
IMAGE="${DAVARNA_WALLET_RELEASE_IMAGE:?Set candidate backend image tag or sha256 ID}"
ROOT=/opt/davarna-v2
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo 'BLOCKED: expected 40-character SHA' >&2; exit 2; }
cd "$ROOT"
git cat-file -e "$REF^{commit}"
docker image inspect "$IMAGE" >/dev/null
echo "===== VERIFY IMAGE EMBEDS EXACT SOURCE FILES ====="
for rel in \
  app/routers/mini_router.py \
  app/services/crypto_chain_service.py \
  app/services/crypto_deposit_service.py \
  app/services/crypto_destination_state.py \
  app/services/crypto_worker.py \
  app/static/mini/index.html \
  app/static/mini/app.js \
  app/static/mini/ux-v2.css; do
  source_hash="$(git show "$REF:backend/$rel" | sha256sum | cut -d' ' -f1)"
  image_hash="$(docker run --rm --network none --read-only --cap-drop ALL \
    --entrypoint sha256sum "$IMAGE" "/app/$rel" | cut -d' ' -f1)"
  if [[ "$source_hash" != "$image_hash" ]]; then
    echo "BLOCKED: image/source mismatch for $rel"
    echo "SOURCE_SHA256=$source_hash"
    echo "IMAGE_SHA256=$image_hash"
    exit 4
  fi
  echo "PASS: $rel"
done
echo "===== PINNED IMAGE SOURCE INTEGRITY PASS ====="
echo "SOURCE=$REF"
echo "IMAGE=$IMAGE"
echo 'No production services or Docker Compose were modified.'
