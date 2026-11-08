#!/usr/bin/env bash
# PR31 production rollout; only backend changes. Requires explicit approved flag.
set -Eeuo pipefail
umask 077
ROOT=/opt/davarna-v2
PROD=/opt/davarna
SOURCE=90f66708e26d999617e130df5550119b8c2ff611
OLD=davarna-backend:forum-mini-e7517922-stage2
OLD_ID=sha256:b6d2709c3f78ce946a90aeb1b2bd6774acfa6b72a88cd604c370842cc3824850
NEW=davarna-backend:finance-pr31-90f6670
BOT=davarna-bot:forum-mini-e7517922-stage2
BACKUPS=/opt/davarna/backups/finance-20261108
RELEASE=/root/davarna-v2-release-backups/pr31-finance-$(date -u +%Y%m%dT%H%M%SZ)
started=0
fail(){ echo "BLOCKER: $*" >&2; exit 2; }
[[ "$(id -u)" == 0 ]] || fail "root required"
[[ "${DAVARNA_PR31_DEPLOY_APPROVAL:-}" == APPROVE_PR31_MIGRATION_PRODUCTION ]] || fail "missing explicit approval"
exec 9>/run/davarna-pr31-deploy.lock
flock -n 9 || fail "deploy lock held"
cd "$ROOT"
git cat-file -e "$SOURCE^{commit}" || fail "missing approved source"
[[ "$(git rev-parse origin/fix/mini-finance-rejection-reasons-20261108)" == "$SOURCE" ]] || fail "PR31 head changed"
[[ "$(docker image inspect -f '{{.Id}}' "$OLD")" == "$OLD_ID" ]] || fail "old image drift"
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$OLD_ID" ]] || fail "running backend drift"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$OLD" ]] || fail "backend tag drift"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == "$BOT" ]] || fail "Bot tag drift"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
 [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || fail "unhealthy: $c"
done
(( $(awk '/^MemAvailable:/ {print $2}' /proc/meminfo) > 650*1024 )) || fail "low available memory"
(( $(df -Pk "$ROOT" | awk 'NR==2 {print $4}') > 3*1024*1024 )) || fail "low free disk"
[[ "$(curl -fsS --max-time 8 http://127.0.0.1:18080/health/db)" == '{"ok":true}' ]] || fail "Production API health failed"
docker exec davarna-mysql sh -ec '
 export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"
 [ "$(mysql -uroot -N -B "$MYSQL_DATABASE" -e "SELECT version_num FROM alembic_version")" = 20261104_0011 ] || exit 2
 [ "$(mysql -uroot -N -B "$MYSQL_DATABASE" -e "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=0x6465706f7369745f7265717565737473 AND column_name=0x72656a656374696f6e5f726561736f6e")" = 0 ] || exit 2
' || fail "unexpected production migration baseline"
echo "PASS: Production preflight healthy; previous revision correct"
label=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' davarna-backend)
IFS=',' read -r -a files <<< "$label"
(( ${#files[@]} >= 2 )) || fail "Compose chain missing"
[[ "${files[0]}" == "$PROD/docker-compose.yml" ]] || fail "unexpected Compose base"
args=()
for f in "${files[@]}"; do
 [[ "$f" == /* && -f "$f" && ! -L "$f" ]] || fail "invalid Compose file"
 case "$f" in "$PROD/"*|"$ROOT/"*|/root/davarna-v2-release-backups/*) ;; *) fail "unexpected Compose path: $f";; esac
 args+=(-f "$f")
done
export TAMBOLA_V2_BACKEND_IMAGE="$OLD" TAMBOLA_V2_BOT_IMAGE="$BOT"
export DAVARNA_UX5_BACKEND_IMAGE="$OLD" DAVARNA_UX5_BOT_IMAGE="$BOT"
mkdir -p "$RELEASE" "$BACKUPS"
chmod 700 "$RELEASE" "$BACKUPS"
printf '%s\n' services: '  backend:' "    image: $NEW" > "$RELEASE/upgrade.yml"
printf '%s\n' services: '  backend:' "    image: $OLD" > "$RELEASE/rollback.yml"
compose(){ (cd "$PROD"; docker compose -p davarna --env-file "$PROD/.env.prod" "${args[@]}" -f "$1" "${@:2}"); }
finish(){ rc=$?; trap - EXIT
 if (( rc != 0 && started == 1 )); then
  echo "ROLLBACK: reverting backend CODE only; do NOT restore live DB" >&2
  compose "$RELEASE/rollback.yml" up -d --no-deps --no-build --force-recreate backend || true
  [[ "$(docker inspect -f '{{.Image}}' davarna-backend 2>/dev/null || true)" == "$OLD_ID" ]] && echo "Old backend image restored" >&2 || echo "CRITICAL: rollback failed" >&2
 fi
 exit "$rc"
}
trap finish EXIT
compose "$RELEASE/upgrade.yml" config --format json > "$RELEASE/compose-effective.json"
python3 - "$RELEASE/compose-effective.json" "$NEW" "$BOT" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))["services"]
assert s["backend"]["image"]==sys.argv[2]
assert s["bot"]["image"]==sys.argv[3]
assert any(str(p.get("published"))=="18080" and p.get("host_ip")=="127.0.0.1" for p in s["backend"]["ports"])
print("PASS: Compose image and localhost port verified")
PY
echo "===== BUILD BACKEND CANDIDATE ====="
[[ ! $(docker image ls -q "$NEW") ]] || fail "candidate image tag exists; refuse overwrite"
WORK=$(mktemp -d /tmp/davarna-pr31-build.XXXXXX)
git archive "$SOURCE" -- backend/alembic/versions/20261108_0012_deposit_rejection_reason.py backend/app/models/finance.py backend/app/routers/mini_router.py backend/app/schemas/mini.py backend/app/static/mini/app.js backend/app/static/mini/index.html backend/app/static/mini/styles.css | tar -x -C "$WORK"
node --check "$WORK/backend/app/static/mini/app.js"
cat > "$WORK/Dockerfile" <<'EOF'
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY backend/alembic/versions/20261108_0012_deposit_rejection_reason.py /app/alembic/versions/
COPY backend/app/models/finance.py /app/app/models/
COPY backend/app/routers/mini_router.py /app/app/routers/
COPY backend/app/schemas/mini.py /app/app/schemas/
COPY backend/app/static/mini/app.js /app/app/static/mini/
COPY backend/app/static/mini/index.html /app/app/static/mini/
COPY backend/app/static/mini/styles.css /app/app/static/mini/
EOF
docker build --network none --pull=false --build-arg "BASE_IMAGE=$OLD" -f "$WORK/Dockerfile" -t "$NEW" "$WORK"
rm -rf -- "$WORK"
NEW_ID=$(docker image inspect -f '{{.Id}}' "$NEW")
echo "$NEW_ID" > "$RELEASE/new-image-id"
echo "$OLD_ID" > "$RELEASE/old-image-id"
docker run --rm --network none --read-only --memory 256m --security-opt no-new-privileges --cap-drop ALL --entrypoint python "$NEW" -c 'import ast,pathlib; ps=["/app/app/routers/mini_router.py","/app/app/models/finance.py","/app/app/schemas/mini.py","/app/alembic/versions/20261108_0012_deposit_rejection_reason.py"]; [ast.parse(pathlib.Path(p).read_text()) for p in ps]; print("PASS: Python syntax")'
echo "===== FRESH PRODUCTION BACKUP ====="
SQL="$BACKUPS/davarna_pr31_$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
docker exec davarna-mysql sh -ec '
 export MYSQL_PWD="$MYSQL_PASSWORD"
 exec mysqldump -u"$MYSQL_USER" --single-transaction --quick --hex-blob --default-character-set=utf8mb4 --routines --triggers --events --no-tablespaces "$MYSQL_DATABASE"
' | gzip -6 > "$SQL.partial"
test -s "$SQL.partial"
gzip -t "$SQL.partial"
[[ "$(gzip -cd "$SQL.partial" | grep -c '^CREATE TABLE ' || true)" == 19 ]] || fail "backup table count mismatch"
chmod 600 "$SQL.partial"; mv "$SQL.partial" "$SQL"
sha256sum "$SQL" > "$RELEASE/backup.sha256"
echo "PASS: fresh backup=$SQL"
echo "===== DEPLOY NEW BACKEND; STARTUP APPLIES 0012 ====="
started=1
compose "$RELEASE/upgrade.yml" up -d --no-deps --no-build --force-recreate backend
ready=0
for i in $(seq 1 40); do
 if [[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-backend 2>/dev/null || true)" == healthy ]] && curl -fsS --max-time 4 http://127.0.0.1:18080/health/db >/dev/null 2>&1; then ready=1; break; fi
 sleep 2
done
(( ready == 1 )) || fail "new backend health failed"
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$NEW_ID" ]] || fail "backend image mismatch"
docker exec davarna-mysql sh -ec '
 export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"
 [ "$(mysql -uroot -N -B "$MYSQL_DATABASE" -e "SELECT version_num FROM alembic_version")" = 20261108_0012 ]
' || fail "migration mismatch"
curl -fsS --max-time 8 -o "$RELEASE/live-index.html" http://127.0.0.1:18080/mini/index.html || fail "Mini HTML request failed"
grep -Fq 'finance-reject-reasons-20261108' "$RELEASE/live-index.html" || fail "Mini App still old"
for c in davarna-bot davarna-mysql davarna-redis; do
 [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || fail "dependency health changed"
done
echo "PASS: PR31 finance backend and migration 20261108_0012 deployed"
echo "Release directory: $RELEASE"
echo "Backup: $SQL"
