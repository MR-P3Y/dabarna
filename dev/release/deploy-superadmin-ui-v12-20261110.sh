#!/usr/bin/env bash
# UI-only V1.2 release. Pinned source, verified backup, code-only automatic rollback.
set -Eeuo pipefail
umask 077
PROD=/opt/davarna
ROOT=/opt/davarna-v2
SOURCE="${DAVARNA_V12_UI_REF:?Pin the UI-only source SHA}"
OLD="davarna-backend:superadmin-v11-rbac-7101e5c"
OLD_ID="sha256:42a77764a254d33f058fb1b606b4a274704975feadce717aa47bb336a3cb9d45"
NEW="davarna-backend:superadmin-ui-v12-${SOURCE:0:7}"
fail() { echo "BLOCKER: $*" >&2; exit 2; }
[[ "${DAVARNA_V12_UI_DEPLOY_APPROVAL:-}" == "APPROVE_UI_ONLY_V12_PRODUCTION" ]] || fail "Explicit UI-only production approval missing"
[[ "$SOURCE" =~ ^[a-f0-9]{40}$ ]] || fail "Invalid source SHA"
[[ "$(id -u)" == 0 ]] || fail "root required"
exec 9>/run/davarna-v12-ui-deploy.lock
flock -n 9 || fail "Another V1.2 release is in progress"
cd "$ROOT"
git cat-file -e "$SOURCE^{commit}" || fail "Expected source commit missing"
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$OLD_ID" ]] || fail "Live Backend image changed"
[[ "$(docker image inspect -f '{{.Id}}' "$OLD")" == "$OLD_ID" ]] || fail "Old image tag changed"
NEW_ID="$(docker image inspect -f '{{.Id}}' "$NEW")" || fail "Candidate image unavailable"
[[ "$NEW_ID" == sha256:* && "$NEW_ID" != "$OLD_ID" ]] || fail "Invalid candidate"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || fail "$c unhealthy"
done
[[ -f "$PROD/.env.prod" ]] || fail "Missing production env file"
[[ "$(curl -fsS --max-time 10 http://127.0.0.1:18080/health/db)" == '{"ok":true}' ]] || fail "DB health failure"
(( $(df -Pk "$PROD" | awk 'NR==2 {print $4}') > 3 * 1024 * 1024 )) || fail "Less than 3GiB disk free"

echo "===== VERIFY IMAGE CONTENTS ====="
for path in app/routers/mini_router.py app/static/mini/index.html app/static/mini/app.js app/static/mini/ux-v2.css; do
  expected="$(git show "$SOURCE:backend/$path" | sha256sum | cut -d' ' -f1)"
  actual="$(docker run --rm --network none --entrypoint sha256sum "$NEW" "/app/$path" | cut -d' ' -f1)"
  [[ "$expected" == "$actual" ]] || fail "Candidate content mismatch: $path"
done
[[ -z "$(git show "$SOURCE:backend/app/routers/mini_router.py" | grep -F 'crypto-address-proposals' || true)" ]] || fail "Unexpected crypto route in UI-only release"
[[ -z "$(git show "$SOURCE:backend/app/static/mini/app.js" | grep -F 'REQUEST_ADDRESS_CHANGE' || true)" ]] || fail "Unexpected crypto write in UI-only release"
echo "PASS: UI-only exact-source candidate"

echo "===== CAPTURE COMPOSE CHAIN ====="
CSV="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' davarna-backend)"
IFS=',' read -r -a FILES <<< "$CSV"
(( ${#FILES[@]} >= 2 )) || fail "Compose chain missing"
[[ "${FILES[0]}" == "$PROD/docker-compose.yml" ]] || fail "Unexpected Compose base"
declare -a ARGS=()
for f in "${FILES[@]}"; do
  [[ "$f" == /* && -f "$f" && ! -L "$f" ]] || fail "Invalid Compose layer: $f"
  ARGS+=(-f "$f")
done
export TAMBOLA_V2_BACKEND_IMAGE=davarna-backend:rbac-pr14-e087c40bd471
export TAMBOLA_V2_BOT_IMAGE=davarna-bot:pr13-d9434cb10d71
export DAVARNA_UX5_BACKEND_IMAGE=davarna-backend:rbac-pr14-e087c40bd471
export DAVARNA_UX5_BOT_IMAGE=davarna-bot:pr13-d9434cb10d71

BACKUP="/root/davarna-v2-release-backups/superadmin-ui-v12-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p -m 0700 "$BACKUP"
printf '%s\n' "$CSV" > "$BACKUP/compose-chain.txt"
printf 'services:\n  backend:\n    image: %s\n' "$OLD" > "$BACKUP/rollback.yml"
printf 'services:\n  backend:\n    image: %s\n' "$NEW" > "$BACKUP/upgrade.yml"
compose() {
  (cd "$PROD" && docker compose -p davarna --env-file "$PROD/.env.prod" "${ARGS[@]}" "$@")
}
echo "===== VALIDATE EFFECTIVE IMAGE-ONLY CHANGE ====="
compose config --format json > "$BACKUP/compose-before.json"
compose -f "$BACKUP/upgrade.yml" config --format json > "$BACKUP/compose-after.json"
python3 - "$BACKUP/compose-before.json" "$BACKUP/compose-after.json" "$OLD" "$NEW" <<'PY'
import json,sys
before=json.load(open(sys.argv[1]))
after=json.load(open(sys.argv[2]))
if before["services"]["backend"].get("image")!=sys.argv[3]: raise SystemExit("BLOCKER: old effective image mismatch")
if after["services"]["backend"].get("image")!=sys.argv[4]: raise SystemExit("BLOCKER: new effective image mismatch")
b=dict(before["services"]["backend"]); a=dict(after["services"]["backend"])
b.pop("image",None); a.pop("image",None)
if b != a: raise SystemExit("BLOCKER: backend Compose settings drift")
for name in before["services"]:
    if name!="backend" and before["services"][name]!=after["services"][name]:
        raise SystemExit("BLOCKER: unrelated Compose changes: "+name)
print("PASS: image-only Compose change")
PY

echo "===== BACKUP DATABASE AND RECEIPTS ====="
docker exec davarna-mysql sh -ec '
  export MYSQL_PWD="$MYSQL_PASSWORD"
  exec mysqldump -u"$MYSQL_USER" --single-transaction --skip-lock-tables --quick --no-tablespaces "$MYSQL_DATABASE"
' | gzip -1 > "$BACKUP/database.sql.gz"
gzip -t "$BACKUP/database.sql.gz"
[[ "$(stat -c %s "$BACKUP/database.sql.gz")" -gt 2048 ]] || fail "Database backup unexpectedly small"
tar -czf "$BACKUP/storage.tar.gz" -C "$PROD" storage davarna-bot/storage
tar -tzf "$BACKUP/storage.tar.gz" >/dev/null
printf '%s\n' "old=$OLD" "old_id=$OLD_ID" "new=$NEW" "new_id=$NEW_ID" "source=$SOURCE" > "$BACKUP/images.txt"
(cd "$BACKUP" && sha256sum database.sql.gz storage.tar.gz > SHA256SUMS && sha256sum -c SHA256SUMS)

STARTED=0
finish() {
  rc=$?
  trap - EXIT
  if (( rc != 0 && STARTED == 1 )); then
    echo "===== CODE-ONLY AUTOMATIC ROLLBACK =====" >&2
    set +e
    compose -f "$BACKUP/rollback.yml" up -d --no-deps --no-build --force-recreate backend
    for _ in $(seq 1 40); do
      state="$(docker inspect -f '{{.State.Health.Status}}' davarna-backend 2>/dev/null || true)"
      image="$(docker inspect -f '{{.Image}}' davarna-backend 2>/dev/null || true)"
      if [[ "$state" == healthy && "$image" == "$OLD_ID" ]]; then
        echo "ROLLBACK VERIFIED: old image healthy" >&2
        exit "$rc"
      fi
      sleep 3
    done
    echo "CRITICAL: rollback was not verified; inspect backend immediately" >&2
  fi
  exit "$rc"
}
trap finish EXIT

echo "===== RELEASE BACKEND UI V1.2 ====="
STARTED=1
compose -f "$BACKUP/upgrade.yml" up -d --no-deps --no-build --force-recreate backend
READY=0
for _ in $(seq 1 40); do
  status="$(docker inspect -f '{{.State.Health.Status}}' davarna-backend 2>/dev/null || true)"
  if [[ "$status" == healthy ]] && [[ "$(curl -fsS --max-time 5 http://127.0.0.1:18080/health/db 2>/dev/null || true)" == '{"ok":true}' ]]; then
    READY=1
    break
  fi
  sleep 3
done
[[ "$READY" == 1 ]] || fail "New backend unhealthy"
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$NEW_ID" ]] || fail "Unexpected running image"
TMP="$(mktemp -d /tmp/davarna-v12-verify.XXXXXX)"
trap 'rm -rf -- "$TMP"; finish' EXIT
for asset in index.html app.js ux-v2.css; do
  curl -fsS --max-time 12 "http://127.0.0.1:18080/mini/$asset" -o "$TMP/$asset" || fail "Mini asset missing: $asset"
  echo "PASS: $asset"
done
grep -Fq "20261110-superadmin-command-v12" "$TMP/index.html" || fail "V1.2 asset revision not served"
HTTP="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 'http://127.0.0.1:18080/mini-api/admin/ops-dashboard')"
[[ "$HTTP" == 401 || "$HTTP" == 403 ]] || fail "Unauthenticated dashboard access not denied: $HTTP"
for c in davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || fail "Service unhealthy: $c"
done
rm -rf -- "$TMP"
trap finish EXIT
echo "===== SUPERADMIN UI V1.2 PRODUCTION RELEASE VERIFIED ====="
echo "RUNNING_IMAGE=$NEW_ID"
echo "BACKUP=$BACKUP"
