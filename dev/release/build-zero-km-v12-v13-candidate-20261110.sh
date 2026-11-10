#!/usr/bin/env bash
# Build V1.2 wallet backend + V1.3 Superadmin UI as a detached, NON-DEPLOYED
# candidate. Fail closed on any patch conflict. Production is never modified.
set -Eeuo pipefail
umask 077
REF="${DAVARNA_ZERO_KM_COMBINED_REF:?Pin exact V1.2 source commit}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo "BLOCKED: invalid SHA" >&2; exit 2; }
[[ "${DAVARNA_ZERO_KM_BUILD_APPROVAL:-}" == "BUILD_NONDEPLOYED_CANDIDATE_ONLY" ]] || {
  echo "BLOCKED: build-only approval missing" >&2; exit 2;
}
ROOT=/opt/davarna-v2
BASE=cf7652dc7b6b4ddfcab167214dacae37aa874ea8
UI_HEAD=247c2bee78f85d54aabec35078312b94c9efcc92
UI_MERGE=13467120109c941bc1f4a5b4e88be1fdabddb479
TAG="davarna-backend:zero-km-combined-${REF:0:12}"
cd "$ROOT"
for sha in "$REF" "$BASE" "$UI_HEAD" "$UI_MERGE"; do
  git cat-file -e "$sha^{commit}" || { echo "BLOCKED: missing source $sha"; exit 2; }
done
[[ -n "$(git diff --name-only "$BASE" "$UI_HEAD" -- backend/app/static/mini/index.html backend/app/static/mini/app.js backend/app/static/mini/ux-v2.css)" ]] || {
  echo "BLOCKED: no V1.3 overlay diff"; exit 3;
}
WORK="$(mktemp -d /tmp/davarna-zero-combined.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
git archive "$REF" | tar -x -C "$WORK"
git diff --binary "$BASE" "$UI_HEAD" -- \
  backend/app/static/mini/index.html \
  backend/app/static/mini/app.js > "$WORK/v13.patch"
echo "===== APPLY V1.3 UI OVER V1.2 WALLET SOURCE ====="
if ! (cd "$WORK" && git apply --check v13.patch); then
  echo "BLOCKED: V1.3 patch conflicts with V1.2; requires explicit source integration" >&2
  exit 4
fi
(cd "$WORK" && git apply v13.patch)
git show "$UI_HEAD:backend/app/static/mini/ux-v2.css" \
  | awk '/^\/\* Superadmin v1\.3:/ {found=1} found {print}' > "$WORK/v13.css"
[[ -s "$WORK/v13.css" ]] || { echo "BLOCKED: V1.3 CSS missing"; exit 4; }
grep -Fq 'Superadmin v1.3:' "$WORK/v13.css"
if grep -Fq 'Superadmin v1.3:' "$WORK/backend/app/static/mini/ux-v2.css"; then
  echo "BLOCKED: V1.3 CSS already present unexpectedly"; exit 4
fi
cat "$WORK/v13.css" >> "$WORK/backend/app/static/mini/ux-v2.css"
git show "$UI_HEAD:backend/tests/js/test_superadmin_sections_v13.mjs" \
  > "$WORK/backend/tests/js/test_superadmin_sections_v13.mjs"

echo "===== COMBINED CONTRACT CHECKS ====="
node --check "$WORK/backend/app/static/mini/app.js"
node "$WORK/backend/tests/js/test_superadmin_sections_v13.mjs"
grep -Fq 'superadmin-workspace-v13' "$WORK/backend/app/static/mini/index.html"
grep -Fq 'DAVARNA_CRYPTO_ROTATION_PRODUCTION' "$WORK/backend/app/services/crypto_destination_state.py"
grep -Fq 'destination_address' "$WORK/backend/app/services/crypto_chain_service.py"
echo "===== BUILD NON-DEPLOYED BACKEND IMAGE ====="
# No direct production mounts, names, ports, DB connections, or Bot startup.
docker build --pull=false --tag "$TAG" -f "$WORK/backend/Dockerfile" "$WORK/backend"
echo "===== VERIFY CANDIDATE IMAGE ====="
for file in \
  app/static/mini/index.html \
  app/static/mini/app.js \
  app/static/mini/ux-v2.css \
  app/services/crypto_destination_state.py \
  app/services/crypto_chain_service.py; do
  a="$(sha256sum "$WORK/backend/$file" | cut -d' ' -f1)"
  b="$(docker run --rm --network none --read-only --entrypoint sha256sum "$TAG" "/app/$file" | cut -d' ' -f1)"
  [[ "$a" == "$b" ]] || { echo "BLOCKED: image mismatch $file"; exit 5; }
  echo "PASS: $file"
done
echo "===== NON-DEPLOYED ZERO-KM COMBINED IMAGE READY ====="
echo "IMAGE=$TAG"
docker image inspect -f 'IMAGE_ID={{.Id}}' "$TAG"
echo "PRODUCTION_UNCHANGED=true"
