#!/usr/bin/env bash
# BUILD ONLY: v1.1 Superadmin dashboard image candidate. No compose, restart, DB, or network.
set -Eeuo pipefail
umask 077
ROOT=/opt/davarna-v2
BRANCH=feature/superadmin-live-dashboard-v11-20261109
APPROVED_UI_REF=f48b124634d97e12b91e914cb333b77eba13132f
BASE_REF=9cb68764c2949d19865555e70c7d1ee257625d28
LIVE_CONTAINER=davarna-backend
BASE_IMAGE=davarna-backend:v1-notices-9cb6876
NEW_IMAGE=davarna-backend:superadmin-v11-f48b124
WORK=''
fail() { echo "BLOCKER: $*" >&2; exit 2; }
cleanup() {
  if [[ -n "$WORK" && -d "$WORK" ]]; then rm -rf -- "$WORK"; fi
}
trap cleanup EXIT
[[ "$(id -u)" == 0 ]] || fail "root required"
cd "$ROOT"
git cat-file -e "$APPROVED_UI_REF^{commit}" || fail "tested UI source commit missing"
git cat-file -e "$BASE_REF^{commit}" || fail "v1 baseline commit missing"
git merge-base --is-ancestor "$BASE_REF" "$APPROVED_UI_REF" || fail "UI source not based on tested v1"
git merge-base --is-ancestor "$APPROVED_UI_REF" "origin/$BRANCH" || fail "UI branch no longer contains approved commit"
[[ "$(docker inspect -f '{{.State.Health.Status}}' "$LIVE_CONTAINER")" == healthy ]] || fail "Production Backend unhealthy"
[[ "$(docker inspect -f '{{.Image}}' "$LIVE_CONTAINER")" == "$(docker image inspect -f '{{.Id}}' "$BASE_IMAGE")" ]] || fail "running image is not pinned v1 notices image"
(( $(df -Pk /opt/davarna | awk 'NR==2 {print $4}') > 5*1024*1024 )) || fail "disk capacity below 5 GiB"
(( $(awk '/^MemAvailable:/ {print $2}' /proc/meminfo) > 700*1024 )) || fail "available memory below 700 MiB"
WORK="$(mktemp -d /tmp/davarna-superadmin-v11-build.XXXXXX)"
mkdir -p "$WORK/backend/app/static/mini"
for filename in index.html app.js ux-v2.css; do
  path="backend/app/static/mini/$filename"
  docker cp "$LIVE_CONTAINER:/app/app/static/mini/$filename" "$WORK/production-$filename" || fail "missing live asset: $filename"
  git show "$BASE_REF:$path" | cmp -s - "$WORK/production-$filename" || fail "Production asset drift: $filename; no build"
done
echo "PASS: all 3 live assets match the approved v1 source baseline"
git archive "$APPROVED_UI_REF" -- \
  backend/app/static/mini/index.html \
  backend/app/static/mini/app.js \
  backend/app/static/mini/ux-v2.css | tar -x -C "$WORK"
cat > "$WORK/Dockerfile" <<'EOF'
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY backend/app/static/mini/index.html /app/app/static/mini/index.html
COPY backend/app/static/mini/app.js /app/app/static/mini/app.js
COPY backend/app/static/mini/ux-v2.css /app/app/static/mini/ux-v2.css
LABEL org.opencontainers.image.title="Davarna v1.1 Superadmin Dashboard Candidate"
EOF
echo "===== BUILD OFFLINE UI-ONLY IMAGE ====="
docker build --pull=false --network=none \
  --build-arg "BASE_IMAGE=$BASE_IMAGE" \
  --file "$WORK/Dockerfile" \
  --tag "$NEW_IMAGE" "$WORK"
echo "===== VERIFY IMAGE CONTENT HASHES (OFFLINE) ====="
expected_index="$(git show "$APPROVED_UI_REF:backend/app/static/mini/index.html" | sha256sum | awk '{print $1}')"
expected_js="$(git show "$APPROVED_UI_REF:backend/app/static/mini/app.js" | sha256sum | awk '{print $1}')"
expected_css="$(git show "$APPROVED_UI_REF:backend/app/static/mini/ux-v2.css" | sha256sum | awk '{print $1}')"
docker run --rm --network none --read-only \
  -e "EXPECTED_INDEX=$expected_index" \
  -e "EXPECTED_JS=$expected_js" \
  -e "EXPECTED_CSS=$expected_css" \
  "$NEW_IMAGE" python -c '
from hashlib import sha256
from pathlib import Path
from os import environ
base = Path("/app/app/static/mini")
for filename, variable in (
    ("index.html", "EXPECTED_INDEX"),
    ("app.js", "EXPECTED_JS"),
    ("ux-v2.css", "EXPECTED_CSS"),
):
    actual = sha256((base / filename).read_bytes()).hexdigest()
    assert actual == environ[variable], f"{filename}: hash mismatch"
    print(f"PASS: {filename} exact tested source")
'
echo "===== VERIFY LIVE BACKEND STILL UNCHANGED ====="
[[ "$(docker inspect -f '{{.State.Health.Status}}' "$LIVE_CONTAINER")" == healthy ]] || fail "Production unhealthy after candidate build"
[[ "$(docker inspect -f '{{.Image}}' "$LIVE_CONTAINER")" == "$(docker image inspect -f '{{.Id}}' "$BASE_IMAGE")" ]] || fail "unexpected Production image change"
docker image inspect -f 'CANDIDATE_IMAGE_ID={{.Id}}' "$NEW_IMAGE"
echo "===== V1.1 IMAGE CANDIDATE VERIFIED — PRODUCTION UNCHANGED ====="
