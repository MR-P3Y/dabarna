#!/usr/bin/env bash
# UI-only Superadmin V1.3 deployment on the exact live Autopilot image.
# Recreates only the backend container; preserves Bot, DB, Redis, worker flags and data.
set -Eeuo pipefail
umask 077

ROOT=/opt/davarna-v2
PROD=/opt/davarna
RELEASE=release/davarna-v1-candidate-20261109
BASE=cf7652dc7b6b4ddfcab167214dacae37aa874ea8
PR_HEAD=247c2bee78f85d54aabec35078312b94c9efcc92
MERGE_SHA=13467120109c941bc1f4a5b4e88be1fdabddb479

OLD_TAG=davarna-backend:auto-clock-92471d0132b4
OLD_ID=sha256:edaf8415a4d9dd148672fbb3a665a00626cada821fa6a478f178a349c70096e4
CANDIDATE_TAG=davarna-backend:superadmin-v13-test-247c2be
CANDIDATE_ID=sha256:4bfe2afa070fa9ca330f70e02ce2233bf2dcf33fb7aa21a1335fc3666cce04e3
NEW_TAG=davarna-backend:superadmin-v13-247c2be

die(){ echo "BLOCKER: $*" >&2; exit 2; }
[[ "${DAVARNA_SUPERADMIN_V13_APPROVAL:-}" == "DEPLOY_SUPERADMIN_V13_UI_ONLY" ]] || die "explicit V1.3 production approval missing"
[[ "$(id -u)" == 0 ]] || die "root required"
[[ -f "$PROD/.env.prod" ]] || die "production env file missing"
cd "$ROOT"

exec 9>/run/davarna-superadmin-v13-deploy.lock
flock -n 9 || die "another release holds lock"

echo "===== VERIFY MERGED SOURCE ====="
git fetch --no-tags origin "$RELEASE"
git cat-file -e "$BASE^{commit}" || die "V1.2 base commit missing"
git cat-file -e "$PR_HEAD^{commit}" || die "PR #45 source commit missing"
git cat-file -e "$MERGE_SHA^{commit}" || die "PR #45 merge commit missing"
git merge-base --is-ancestor "$MERGE_SHA" FETCH_HEAD || die "PR #45 is not in release branch"
git diff --quiet "$PR_HEAD" "$MERGE_SHA" -- \
  backend/app/static/mini/index.html \
  backend/app/static/mini/app.js \
  backend/app/static/mini/ux-v2.css \
  backend/tests/js/test_superadmin_sections_v13.mjs \
  || die "merged release assets differ from tested PR #45"
git diff --check "$BASE" "$PR_HEAD" -- \
  backend/app/static/mini/index.html \
  backend/app/static/mini/app.js \
  backend/app/static/mini/ux-v2.css \
  || die "PR #45 whitespace check failed"

echo "===== VERIFY LIVE SERVICES AND IMAGES ====="
for svc in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$svc")" == healthy ]] || die "unhealthy service: $svc"
done
LIVE_TAG="$(docker inspect -f '{{.Config.Image}}' davarna-backend)"
LIVE_ID="$(docker inspect -f '{{.Image}}' davarna-backend)"
[[ "$LIVE_TAG" == "$OLD_TAG" ]] || die "live backend tag drift: $LIVE_TAG"
[[ "$LIVE_ID" == "$OLD_ID" ]] || die "live backend image drift: $LIVE_ID"
[[ "$(docker image inspect -f '{{.Id}}' "$OLD_TAG")" == "$OLD_ID" ]] || die "old image tag drift"
[[ "$(docker image inspect -f '{{.Id}}' "$CANDIDATE_TAG")" == "$CANDIDATE_ID" ]] || die "V1.3 candidate missing or changed"

LIVE_BOT_TAG="$(docker inspect -f '{{.Config.Image}}' davarna-bot)"
LIVE_BOT_ID="$(docker inspect -f '{{.Image}}' davarna-bot)"
[[ "$(docker image inspect -f '{{.Id}}' "$LIVE_BOT_TAG")" == "$LIVE_BOT_ID" ]] || die "Bot image tag drift"

BASE_FLAGS="$(docker exec davarna-backend python -c 'from app.core import config as c; print(int(c.GAME_AUTO_DRAW_ENABLED),int(c.GAME_AUTOPILOT_RUNTIME_ENABLED))')"
[[ "$BASE_FLAGS" == "1 0" || "$BASE_FLAGS" == "1 1" ]] || die "unsupported live worker flags: $BASE_FLAGS"
echo "PASS: preserving live worker flags: $BASE_FLAGS"
echo "NOTE: this UI-only deploy briefly recreates backend; test AUTO games are not modified or closed."

echo "===== VERIFY CANDIDATE ASSETS AGAINST LIVE OVERLAY ====="
WORK="$(mktemp -d /tmp/davarna-superadmin-v13-release.XXXXXX)"
BACKUP="/root/davarna-v2-release-backups/superadmin-v13-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p -m 0700 "$BACKUP"
STARTED=0

finish() {
  rc=$?
  trap - EXIT
  if (( rc != 0 && STARTED == 1 )); then
    echo "===== AUTOMATIC BACKEND IMAGE ROLLBACK =====" >&2
    set +e
    compose -f "$BACKUP/rollback.yml" up -d --no-deps --no-build --force-recreate backend
    restored=0
    for _ in $(seq 1 45); do
      state="$(docker inspect -f '{{.State.Health.Status}}' davarna-backend 2>/dev/null || true)"
      image="$(docker inspect -f '{{.Image}}' davarna-backend 2>/dev/null || true)"
      if [[ "$state" == "healthy" && "$image" == "$OLD_ID" ]]; then
        restored=1
        break
      fi
      sleep 2
    done
    if [[ "$restored" == 1 ]]; then
      echo "ROLLBACK VERIFIED: original backend image healthy" >&2
    else
      echo "CRITICAL: rollback not verified; inspect backend immediately" >&2
    fi
  fi
  rm -rf -- "$WORK"
  exit "$rc"
}
trap finish EXIT

mkdir -p "$WORK/backend/app/static/mini" "$WORK/backend/tests/js"
for name in index.html app.js ux-v2.css; do
  docker cp "davarna-backend:/app/app/static/mini/$name" "$WORK/backend/app/static/mini/$name"
done

git diff --binary "$BASE" "$PR_HEAD" -- \
  backend/app/static/mini/index.html \
  backend/app/static/mini/app.js > "$WORK/ui.patch"
(
  cd "$WORK"
  git apply --check ui.patch
  git apply ui.patch
)

git show "$PR_HEAD:backend/app/static/mini/ux-v2.css" |
  awk '/^\/\* Superadmin v1\.3:/ {found=1} found {print}' > "$WORK/v13.css"
[[ -s "$WORK/v13.css" ]] || die "V1.3 CSS section missing"
cat "$WORK/v13.css" >> "$WORK/backend/app/static/mini/ux-v2.css"

git show "$PR_HEAD:backend/tests/js/test_superadmin_sections_v13.mjs" \
  > "$WORK/backend/tests/js/test_superadmin_sections_v13.mjs"
node --check "$WORK/backend/app/static/mini/app.js"
node "$WORK/backend/tests/js/test_superadmin_sections_v13.mjs"

for path in app/static/mini/index.html app/static/mini/app.js app/static/mini/ux-v2.css; do
  expected="$(sha256sum "$WORK/backend/$path" | awk '{print $1}')"
  actual="$(docker run --rm --network none --entrypoint sha256sum "$CANDIDATE_TAG" "/app/$path" | awk '{print $1}')"
  [[ "$expected" == "$actual" ]] || die "candidate asset differs from tested overlay: $path"
  echo "PASS: candidate $path"
done
old_router="$(docker run --rm --network none --entrypoint sha256sum "$OLD_TAG" /app/app/routers/mini_router.py | awk '{print $1}')"
new_router="$(docker run --rm --network none --entrypoint sha256sum "$CANDIDATE_TAG" /app/app/routers/mini_router.py | awk '{print $1}')"
[[ "$old_router" == "$new_router" ]] || die "candidate router differs from live image"

echo "===== PREPARE BACKUP AND COMPOSE OVERLAY ====="
if docker image inspect "$NEW_TAG" >/dev/null 2>&1; then
  [[ "$(docker image inspect -f '{{.Id}}' "$NEW_TAG")" == "$CANDIDATE_ID" ]] || die "release image tag already exists with different image"
else
  docker tag "$CANDIDATE_TAG" "$NEW_TAG"
fi

chain="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' davarna-backend)"
[[ -n "$chain" && "$chain" != "<no value>" ]] || die "Compose chain missing"
IFS=',' read -r -a FILES <<< "$chain"
(( ${#FILES[@]} >= 2 )) || die "unexpected Compose chain"
[[ "${FILES[0]}" == "$PROD/docker-compose.yml" ]] || die "unexpected Compose base"
args=()
for f in "${FILES[@]}"; do
  [[ "$f" = /* && -f "$f" && ! -L "$f" ]] || die "unsafe or missing Compose file: $f"
  args+=(-f "$f")
done

export TAMBOLA_V2_BACKEND_IMAGE="$LIVE_TAG"
export TAMBOLA_V2_BOT_IMAGE="$LIVE_BOT_TAG"
export DAVARNA_UX5_BACKEND_IMAGE="$LIVE_TAG"
export DAVARNA_UX5_BOT_IMAGE="$LIVE_BOT_TAG"

compose() {
  (cd "$PROD" && docker compose -p davarna --env-file "$PROD/.env.prod" "${args[@]}" "$@")
}

printf '%s\n' "$chain" > "$BACKUP/compose-chain.txt"
printf '%s\n' \
  "old_tag=$OLD_TAG" "old_id=$OLD_ID" \
  "new_tag=$NEW_TAG" "new_id=$CANDIDATE_ID" \
  "source_pr_head=$PR_HEAD" "merge_commit=$MERGE_SHA" > "$BACKUP/images.txt"
printf 'services:\n  backend:\n    image: "%s"\n' "$OLD_TAG" > "$BACKUP/rollback.yml"
printf 'services:\n  backend:\n    image: "%s"\n' "$NEW_TAG" > "$BACKUP/upgrade.yml"

compose config --format json > "$WORK/compose-before.json"
compose -f "$BACKUP/upgrade.yml" config --format json > "$WORK/compose-after.json"
python3 - "$WORK/compose-before.json" "$WORK/compose-after.json" "$OLD_TAG" "$NEW_TAG" <<'PY'
import json, sys
before = json.load(open(sys.argv[1]))
after = json.load(open(sys.argv[2]))
if before["services"]["backend"].get("image") != sys.argv[3]:
    raise SystemExit("BLOCKER: effective live backend image mismatch")
if after["services"]["backend"].get("image") != sys.argv[4]:
    raise SystemExit("BLOCKER: candidate backend image not resolved")
after["services"]["backend"]["image"] = before["services"]["backend"]["image"]
if before != after:
    raise SystemExit("BLOCKER: Compose changes something other than backend image")
print("PASS: only backend image changes in effective Compose config")
PY

echo "===== FINAL PRE-DEPLOY GUARDS ====="
for svc in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$svc")" == healthy ]] || die "service became unhealthy: $svc"
done
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$OLD_ID" ]] || die "backend image changed during preflight"
FLAGS="$(docker exec davarna-backend python -c 'from app.core import config as c; print(int(c.GAME_AUTO_DRAW_ENABLED),int(c.GAME_AUTOPILOT_RUNTIME_ENABLED))')"
[[ "$FLAGS" == "$BASE_FLAGS" ]] || die "worker flags changed during preflight: before=$BASE_FLAGS now=$FLAGS"

echo "===== DEPLOY UI-ONLY V1.3: BACKEND CONTAINER ONLY ====="
STARTED=1
compose -f "$BACKUP/upgrade.yml" up -d --no-deps --no-build --force-recreate backend

READY=0
for _ in $(seq 1 45); do
  status="$(docker inspect -f '{{.State.Health.Status}}' davarna-backend 2>/dev/null || true)"
  image="$(docker inspect -f '{{.Image}}' davarna-backend 2>/dev/null || true)"
  if [[ "$status" == "healthy" && "$image" == "$CANDIDATE_ID" ]] &&
     [[ "$(curl -fsS --max-time 5 http://127.0.0.1:18080/health/db 2>/dev/null || true)" == '{"ok":true}' ]]; then
    READY=1
    break
  fi
  sleep 2
done
[[ "$READY" == 1 ]] || die "new backend did not become healthy on candidate image"

echo "===== VERIFY DEPLOYED UI ====="
TMP="$WORK/deployed"
mkdir -p "$TMP"
for asset in index.html app.js ux-v2.css; do
  curl -fsS --max-time 12 "http://127.0.0.1:18080/mini/$asset" -o "$TMP/$asset" || die "asset unavailable: $asset"
done
grep -Fq 'superadmin-workspace-v13' "$TMP/index.html" || die "V1.3 HTML not served"
grep -Fq 'showSuperAdminPanelV13' "$TMP/app.js" || die "V1.3 JS not served"
grep -Fq 'Superadmin v1.3: five categorized workspaces' "$TMP/ux-v2.css" || die "V1.3 CSS not served"

HTTP="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:18080/mini-api/admin/ops-dashboard)"
[[ "$HTTP" == 401 || "$HTTP" == 403 ]] || die "unauthenticated dashboard API access not denied: $HTTP"

FLAGS="$(docker exec davarna-backend python -c 'from app.core import config as c; print(int(c.GAME_AUTO_DRAW_ENABLED),int(c.GAME_AUTOPILOT_RUNTIME_ENABLED))')"
[[ "$FLAGS" == "$BASE_FLAGS" ]] || die "worker flags changed after deployment: before=$BASE_FLAGS now=$FLAGS"
for svc in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$svc")" == healthy ]] || die "post-deploy unhealthy service: $svc"
done

STARTED=0
echo "===== SUPERADMIN V1.3 PRODUCTION DEPLOY PASS ====="
echo "SOURCE_MERGE=$MERGE_SHA"
echo "IMAGE=$NEW_TAG"
echo "IMAGE_ID=$CANDIDATE_ID"
echo "BACKUP=$BACKUP"
