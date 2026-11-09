#!/usr/bin/env bash
# Pinned, isolated UI-only V1.2 verification/build. Does not change Production.
set -Eeuo pipefail
umask 077
ROOT=/opt/davarna-v2
SOURCE="\${DAVARNA_V12_UI_REF:?Set exact verified commit SHA}"
BASE="davarna-backend:superadmin-v11-rbac-7101e5c"
BASE_ID="sha256:42a77764a254d33f058fb1b606b4a274704975feadce717aa47bb336a3cb9d45"
[[ "$SOURCE" =~ ^[a-f0-9]{40}$ ]] || { echo "BLOCKER: invalid SHA"; exit 2; }
cd "$ROOT"
git cat-file -e "$SOURCE^{commit}"
[[ "$(docker image inspect -f '{{.Id}}' "$BASE")" == "$BASE_ID" ]] || { echo "BLOCKER: deployed base image mismatch"; exit 2; }
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$BASE_ID" ]] || { echo "BLOCKER: production backend changed"; exit 2; }
WORK="$(mktemp -d /tmp/davarna-v12-ui.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
git archive "$SOURCE" -- backend/app/static/mini/index.html backend/app/static/mini/app.js backend/app/static/mini/ux-v2.css backend/app/routers/mini_router.py backend/tests/js/test_superadmin_dashboard_v11.mjs backend/tests/test_mini_ops_dashboard_rbac_http.py | tar -x -C "$WORK"
echo "===== NO WALLET CODE IN UI RELEASE ====="
if grep -F -e 'crypto-address-proposals' -e 'REQUEST_ADDRESS_CHANGE' "$WORK/backend/app/routers/mini_router.py" "$WORK/backend/app/static/mini/app.js"; then
  echo "BLOCKER: wallet proposal leaked into UI-only release" >&2
  exit 2
fi
echo "===== JS SYNTAX & UI CONTRACT ====="
node --check "$WORK/backend/app/static/mini/app.js"
node "$WORK/backend/tests/js/test_superadmin_dashboard_v11.mjs"
echo "===== ISOLATED HTTP RBAC ====="
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,size=128m \
  -e DATABASE_URL=sqlite+pysqlite:///:memory: \
  -e REDIS_URL=redis://127.0.0.1:6379/15 \
  -e RECEIPTS_DIR=/tmp/receipts \
  -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
  -e GAME_AUTO_DRAW_ENABLED=false \
  -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
  -v "$WORK/backend:/app:ro" -w /app --entrypoint python "$BASE" \
  -m unittest discover -s tests -p 'test_mini_ops_dashboard_rbac_http.py' -v
echo "===== BUILD CANDIDATE FROM TESTED V1.1 IMAGE ====="
TAG="davarna-backend:superadmin-ui-v12-\${SOURCE:0:7}"
cat > "$WORK/Dockerfile" <<'DOCKERFILE'
ARG BASE_IMAGE=davarna-backend:superadmin-v11-rbac-7101e5c
FROM \${BASE_IMAGE}
COPY backend/app/routers/mini_router.py /app/app/routers/mini_router.py
COPY backend/app/static/mini/index.html /app/app/static/mini/index.html
COPY backend/app/static/mini/app.js /app/app/static/mini/app.js
COPY backend/app/static/mini/ux-v2.css /app/app/static/mini/ux-v2.css
DOCKERFILE
docker build --pull=false --build-arg "BASE_IMAGE=$BASE" -f "$WORK/Dockerfile" -t "$TAG" "$WORK"
echo "===== VERIFY CANDIDATE SOURCE SHA256 ====="
for f in app/routers/mini_router.py app/static/mini/index.html app/static/mini/app.js app/static/mini/ux-v2.css; do
  a="$(sha256sum "$WORK/backend/$f" | cut -d' ' -f1)"
  b="$(docker run --rm --network none --entrypoint sha256sum "$TAG" "/app/$f" | cut -d' ' -f1)"
  [[ "$a" == "$b" ]] || { echo "BLOCKER: candidate file mismatch $f"; exit 2; }
  echo "PASS: $f"
done
echo "===== PRODUCTION HEALTH (UNCHANGED) ====="
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || { echo "BLOCKER: unhealthy $c"; exit 2; }
done
echo "===== V1.2 UI CANDIDATE VERIFIED ====="
echo "TAG=$TAG"
echo "IMAGE_ID=$(docker image inspect -f '{{.Id}}' "$TAG")"