#!/usr/bin/env bash
# Controlled backend-only PR14 RBAC deployment; never changes runtime payment/game flags.
set -Eeuo pipefail
umask 077
ROOT=/opt/davarna-v2
PROD=/opt/davarna
OLD_SOURCE=d9434cb10d714648b4399d1615b916d8e144a156
SOURCE=e087c40bd4714dbc703e48d7bc1f24bd9c35d9aa
BASE=$PROD/docker-compose.yml
INACTIVE=$ROOT/deploy/tambola-v2-inactive.compose.yml
MANUAL=/root/davarna-v2-release-backups/tambola-v2-manual.compose.yml
UX5_OVERRIDE=$ROOT/dev/release/ux5-candidate.compose.yml
PR13_UPGRADE=/root/davarna-v2-release-backups/pr13-d9434cb10d71-20261106T183004Z/upgrade.yml
OLD_BACKEND=davarna-backend:pr13-d9434cb10d71
OLD_BOT=davarna-bot:pr13-d9434cb10d71
NEW_BACKEND=davarna-backend:rbac-pr14-e087c40bd471
NEW_BOT=davarna-bot:pr13-d9434cb10d71
BACKUP=/root/davarna-v2-release-backups/rbac-pr14-e087c40bd471-$(date -u +%Y%m%dT%H%M%SZ)
TMP=
STARTED=0
BOT_STARTED=0
fail(){ echo "BLOCKER: $*" >&2; exit 2; }
# Preserve the Compose layers recorded on the live containers; no unknown layers.
declare -a BACKEND_FILES=()
declare -a BOT_FILES=()
load_live_compose_chain(){
  local container="$1" array_name="$2"
  local csv
  csv="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$container")" || fail "cannot inspect $container Compose chain"
  [[ -n "$csv" && "$csv" != "<no value>" ]] || fail "$container Compose chain unavailable"
  local -a files=()
  IFS=',' read -r -a files <<< "$csv"
  (( ${#files[@]} >= 2 )) || fail "$container Compose chain too short"
  [[ "${files[0]}" == "$BASE" && "${files[1]}" == "$INACTIVE" ]] || fail "$container base/inactive Compose order changed"
  local seen_manual=0
  local seen_pr13=0
  local -A seen=()
  local file
  for file in "${files[@]}"; do
    [[ "$file" == /* && -f "$file" ]] || fail "$container missing Compose file: $file"
    [[ -z "${seen[$file]+set}" ]] || fail "$container duplicate Compose file: $file"
    seen[$file]=1
    case "$file" in
      "$BASE"|"$INACTIVE"|"$UX5_OVERRIDE") ;;
      "$MANUAL") ((seen_manual+=1));;
      "$PR13_UPGRADE")
        # PR13 appended this exact image-only overlay to both live services.
        # Validate bytes, not only the path: never trust changed private files.
        printf '%s\n' \
          'services:' \
          '  backend:' \
          '    image: davarna-backend:pr13-d9434cb10d71' \
          '  bot:' \
          '    image: davarna-bot:pr13-d9434cb10d71' \
          | cmp -s - "$file" || fail "PR13 Compose overlay content mismatch"
        ((seen_pr13+=1))
        ;;
      *) fail "$container has unapproved Compose overlay: $file";;
    esac
  done
  (( seen_pr13 == 1 )) || fail "$container PR13 deployed overlay missing or duplicated"
  [[ "${files[${#files[@]}-1]}" == "$PR13_UPGRADE" ]] || fail "$container PR13 overlay is not the final existing Compose layer"
  if [[ "$container" == davarna-backend ]]; then
    (( seen_manual == 1 )) || fail "backend manual V2 configuration missing"
  else
    (( seen_manual == 0 )) || fail "bot unexpectedly includes backend manual configuration"
  fi
  local -n result="$array_name"
  result=("${files[@]}")
  echo "PASS: $container recognized ${#files[@]} existing Compose layers (order preserved)"
}
backend_compose(){
  local override="$1"; shift
  local -a flags=()
  local file
  for file in "${BACKEND_FILES[@]}"; do flags+=(-f "$file"); done
  (cd "$PROD"; docker compose -p davarna --env-file "$PROD/.env.prod" "${flags[@]}" -f "$override" "$@")
}
bot_compose(){
  local override="$1"; shift
  local -a flags=()
  local file
  for file in "${BOT_FILES[@]}"; do flags+=(-f "$file"); done
  (cd "$PROD"; docker compose -p davarna --env-file "$PROD/.env.prod" "${flags[@]}" -f "$override" "$@")
}
finish(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && STARTED == 1 )); then
    echo "===== AUTO ROLLBACK STARTED =====" >&2
    set +e
    backend_compose "$BACKUP/rollback.yml" up -d --no-build --no-deps --force-recreate backend
    if (( BOT_STARTED )); then
      bot_compose "$BACKUP/rollback.yml" up -d --no-build --no-deps --force-recreate bot
    fi
    echo "===== ROLLBACK ATTEMPTED: VERIFY HEALTH =====" >&2
  fi
  if [[ -n "$TMP" && -d "$TMP" ]]; then rm -rf -- "$TMP"; fi
  exit "$rc"
}
trap finish EXIT
[[ "$(id -u)" == 0 ]] || fail "root required"
cd "$ROOT"
[[ "$(git branch --show-current)" == feature/ui-ux-refresh-tambola-v2-20261106 ]] || fail "wrong branch"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail "dirty tracked worktree"
git merge-base --is-ancestor "$SOURCE" origin/feature/ui-ux-refresh-tambola-v2-20261106 || fail "pinned RBAC source unavailable on remote branch"
EXPECTED=$(printf '%s\n' backend/app/routers/admin_autopilot_router.py backend/app/routers/mini_router.py | sort)
ACTUAL=$(git diff --name-only "$OLD_SOURCE" "$SOURCE" -- backend/app | sort)
[[ "$ACTUAL" == "$EXPECTED" ]] || fail "unreviewed backend changes since PR13"
git diff --quiet "$OLD_SOURCE" "$SOURCE" -- davarna-bot/bot || fail "unreviewed bot changes"
for f in "$BASE" "$INACTIVE" "$MANUAL" "$PROD/.env.prod" "$PROD/davarna-bot/.env.prod"; do
  [[ -f "$f" ]] || fail "missing production file $f"
done
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Running}}' "$c")" == true ]] || fail "$c not running"
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || fail "$c unhealthy"
done
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$OLD_BACKEND" ]] || fail "backend baseline changed"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == "$OLD_BOT" ]] || fail "bot baseline changed"
load_live_compose_chain davarna-backend BACKEND_FILES
load_live_compose_chain davarna-bot BOT_FILES
[[ "$(curl -fsS --max-time 8 http://127.0.0.1:18080/health/db)" == '{"ok":true}' ]] || fail "backend DB health check failed"
for image in "$NEW_BACKEND"; do
  ! docker image inspect "$image" >/dev/null 2>&1 || fail "candidate tag already exists: $image"
done
check_runtime(){
  docker exec -i davarna-backend python - <<'PY'
from app.core import config as cfg
from app.core.db import engine
flags = (bool(cfg.GAME_TAMBOLA_V2_ENABLED),
         bool(cfg.GAME_AUTO_DRAW_ENABLED),
         bool(cfg.GAME_AUTOPILOT_RUNTIME_ENABLED))
if flags != (True, False, False):
    raise SystemExit(f"BLOCKER: effective game flags changed: {flags}")
with engine.connect() as db:
    db.exec_driver_sql("START TRANSACTION READ ONLY")
    try:
        rev = db.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
    finally:
        db.rollback()
if rev != "20261104_0011":
    raise SystemExit(f"BLOCKER: unexpected migration revision {rev}")
print("PASS: runtime flags and schema unchanged")
PY
}
check_runtime
(( $(df -Pk "$PROD" | awk 'NR==2 {print $4}') > 3 * 1024 * 1024 )) || fail "less than 3GiB free disk"
mkdir -p -m 0700 "$BACKUP"
TMP=$(mktemp -d /tmp/davarna-pr13-deploy.XXXXXX)
chmod 0700 "$TMP"
echo "===== BACKUP DATABASE + RECEIPTS ====="
docker exec davarna-mysql sh -c 'exec mysqldump --single-transaction --skip-lock-tables --no-tablespaces -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' | gzip -1 > "$BACKUP/database.sql.gz"
gzip -t "$BACKUP/database.sql.gz"
tar -czf "$BACKUP/storage.tar.gz" -C "$PROD" storage davarna-bot/storage
tar -tzf "$BACKUP/storage.tar.gz" >/dev/null
(cd "$BACKUP"; sha256sum database.sql.gz storage.tar.gz > SHA256SUMS)
docker image tag "$OLD_BACKEND" davarna-backend:rollback-rbac-pr14-e087c40bd471
cat > "$BACKUP/rollback.yml" <<'EOF'
services:
  backend:
    image: davarna-backend:rollback-rbac-pr14-e087c40bd471
EOF
cat > "$BACKUP/upgrade.yml" <<'EOF'
services:
  backend:
    image: davarna-backend:rbac-pr14-e087c40bd471
  bot:
    image: davarna-bot:pr13-d9434cb10d71
EOF
echo "===== STAGE TWO REVIEWED RBAC ROUTERS ONLY ====="
git archive "$SOURCE" -- \
  backend/app/routers/admin_autopilot_router.py \
  backend/app/routers/mini_router.py \
  backend/tests/test_autopilot_commission_rbac.py | tar -x -C "$TMP"
cat > "$TMP/backend.Dockerfile" <<'EOF'
ARG BASE_IMAGE
FROM $BASE_IMAGE
COPY backend/app/routers/admin_autopilot_router.py /app/app/routers/admin_autopilot_router.py
COPY backend/app/routers/mini_router.py /app/app/routers/mini_router.py
EOF
docker build --network none --pull=false -f "$TMP/backend.Dockerfile" \
  --build-arg "BASE_IMAGE=$OLD_BACKEND" -t "$NEW_BACKEND" "$TMP"
docker run --rm --network none --entrypoint python "$NEW_BACKEND" \
  -m compileall -q /app/app/routers/admin_autopilot_router.py /app/app/routers/mini_router.py
echo "===== RUN SIX RBAC TESTS AGAINST NEW IMAGE ====="
docker run --rm --network none --read-only --memory 512m \
  --tmpfs /tmp:rw,nosuid,nodev \
  --entrypoint python -e DATABASE_URL='sqlite+pysqlite:///:memory:' \
  -e REDIS_URL='redis://127.0.0.1:6379/0' \
  -e RECEIPTS_DIR=/tmp/receipts -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$TMP/backend/tests:/offline-tests:ro" -w /app "$NEW_BACKEND" \
  -m unittest discover -s /offline-tests -p test_autopilot_commission_rbac.py -v
export TAMBOLA_V2_BACKEND_IMAGE="$OLD_BACKEND"
export TAMBOLA_V2_BOT_IMAGE="$OLD_BOT"
export DAVARNA_UX5_BACKEND_IMAGE="$OLD_BACKEND"
export DAVARNA_UX5_BOT_IMAGE="$OLD_BOT"
echo "===== CHECK EFFECTIVE COMPOSE (PRIVATE) ====="
backend_compose "$BACKUP/upgrade.yml" config --format json > "$TMP/backend.json"
bot_compose "$BACKUP/upgrade.yml" config --format json > "$TMP/bot.json"
python3 - "$TMP/backend.json" "$TMP/bot.json" "$NEW_BACKEND" "$NEW_BOT" <<'PY'
import json, subprocess, sys
for kind, path, tag in (("backend",sys.argv[1],sys.argv[3]), ("bot",sys.argv[2],sys.argv[4])):
    c = json.load(open(path, encoding="utf-8"))["services"][kind]
    live = json.loads(subprocess.check_output(["docker","inspect","davarna-"+kind],text=True))[0]
    img = json.loads(subprocess.check_output(["docker","image","inspect",tag],text=True))[0]
    def envmap(rows):
        return {v.split("=",1)[0]:v.split("=",1)[1] for v in (rows or []) if "=" in v}
    env = envmap(img["Config"].get("Env"))
    for k,v in (c.get("environment") or {}).items():
        if v is None: env.pop(k,None)
        else: env[k] = str(v)
    if env != envmap(live["Config"].get("Env")):
        raise SystemExit(f"BLOCKER: {kind} environment changed")
    if c.get("image") != tag:
        raise SystemExit(f"BLOCKER: {kind} image changed by override")
    liveports={(p,b.get("HostIp") or "0.0.0.0",str(b.get("HostPort") or ""))
               for p,bs in (live["HostConfig"].get("PortBindings") or {}).items() for b in (bs or [])}
    desiredports={(str(p["target"])+"/"+str(p.get("protocol") or "tcp"),
                   str(p.get("host_ip") or "0.0.0.0"),str(p["published"]))
                  for p in (c.get("ports") or [])}
    if liveports != desiredports:
        raise SystemExit(f"BLOCKER: {kind} published ports changed")
    lm={(v.get("Type"),v.get("Source"),v.get("Destination"),not v.get("RW",True)) for v in (live.get("Mounts") or [])}
    cm={(v.get("type"),v.get("source"),v.get("target"),bool(v.get("read_only",False))) for v in (c.get("volumes") or [])}
    if lm != cm:
        raise SystemExit(f"BLOCKER: {kind} storage mounts changed")
    print("PASS:", kind, "image-only change")
PY
echo "===== DEPLOY BACKEND ====="
STARTED=1
backend_compose "$BACKUP/upgrade.yml" up -d --no-deps --no-build --force-recreate backend
ready=0
for _ in $(seq 1 40); do
  if [[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-backend 2>/dev/null || true)" == healthy ]] &&
     curl -fsS --max-time 4 http://127.0.0.1:18080/health/db >/dev/null; then
    ready=1; break
  fi
  sleep 2
done
(( ready == 1 )) || fail "backend health failed"
docker exec davarna-backend grep -q 'payments-admin-wave1-20261106' /app/app/static/mini/index.html || fail "updated Mini App not found"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$NEW_BACKEND" ]] || fail "backend image mismatch"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == "$OLD_BOT" ]] || fail "bot image unexpectedly changed"
check_runtime
docker exec -i davarna-backend python - <<'PY'
from app.routers import admin_autopilot_router, mini_router
import inspect
a = inspect.getsource(admin_autopilot_router.update_autopilot_config)
m = inspect.getsource(mini_router.mini_admin_update_autopilot_config)
assert "allow_commission_change=ident.scope == AdminScope.SUPER_ADMIN" in a
assert "allow_commission_change=bool(ident.is_super_admin)" in m
print("PASS: commission RBAC loaded in backend")
PY
echo "===== PR14 BACKEND-ONLY DEPLOYED SUCCESSFULLY ====="
docker ps --filter name=davarna-backend --filter name=davarna-bot --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
echo "Protected backup and rollback config: $BACKUP"
