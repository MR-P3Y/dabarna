#!/usr/bin/env bash
# Controlled PR13 production deployment; never touches runtime payment/game flags.
set -Eeuo pipefail
umask 077
ROOT=/opt/davarna-v2
PROD=/opt/davarna
SOURCE=d9434cb10d714648b4399d1615b916d8e144a156
BASE=$PROD/docker-compose.yml
INACTIVE=$ROOT/deploy/tambola-v2-inactive.compose.yml
MANUAL=/root/davarna-v2-release-backups/tambola-v2-manual.compose.yml
OLD_BACKEND=davarna-backend:ux5-f3c649e22593
OLD_BOT=davarna-bot:ux5-f3c649e22593
NEW_BACKEND=davarna-backend:pr13-d9434cb10d71
NEW_BOT=davarna-bot:pr13-d9434cb10d71
BACKUP=/root/davarna-v2-release-backups/pr13-d9434cb10d71-$(date -u +%Y%m%dT%H%M%SZ)
TMP=
STARTED=0
BOT_STARTED=0
fail(){ echo "BLOCKER: $*" >&2; exit 2; }
backend_compose(){
  local override="$1"; shift
  (cd "$PROD"; docker compose -p davarna --env-file "$PROD/.env.prod" -f "$BASE" -f "$INACTIVE" -f "$MANUAL" -f "$override" "$@")
}
bot_compose(){
  local override="$1"; shift
  (cd "$PROD"; docker compose -p davarna --env-file "$PROD/.env.prod" -f "$BASE" -f "$INACTIVE" -f "$override" "$@")
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
git merge-base --is-ancestor "$SOURCE" HEAD || fail "PR13 not merged in checkout"
git diff --quiet "$SOURCE" HEAD -- backend/app davarna-bot/bot || fail "production source changed since PR13"
for f in "$BASE" "$INACTIVE" "$MANUAL" "$PROD/.env.prod" "$PROD/davarna-bot/.env.prod"; do
  [[ -f "$f" ]] || fail "missing production file $f"
done
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Running}}' "$c")" == true ]] || fail "$c not running"
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || fail "$c unhealthy"
done
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$OLD_BACKEND" ]] || fail "backend baseline changed"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == "$OLD_BOT" ]] || fail "bot baseline changed"
[[ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' davarna-backend)" == "$BASE,$INACTIVE,$MANUAL" ]] || fail "backend compose chain changed"
[[ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' davarna-bot)" == "$BASE,$INACTIVE" ]] || fail "bot compose chain changed"
[[ "$(curl -fsS --max-time 8 http://127.0.0.1:18080/health/db)" == '{"ok":true}' ]] || fail "backend DB health check failed"
for image in "$NEW_BACKEND" "$NEW_BOT"; do
  ! docker image inspect "$image" >/dev/null 2>&1 || fail "candidate tag already exists: $image"
done
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
docker image tag "$OLD_BACKEND" davarna-backend:rollback-pr13-d9434cb10d71
docker image tag "$OLD_BOT" davarna-bot:rollback-pr13-d9434cb10d71
cat > "$BACKUP/rollback.yml" <<'EOF'
services:
  backend:
    image: davarna-backend:rollback-pr13-d9434cb10d71
  bot:
    image: davarna-bot:rollback-pr13-d9434cb10d71
EOF
cat > "$BACKUP/upgrade.yml" <<'EOF'
services:
  backend:
    image: davarna-backend:pr13-d9434cb10d71
  bot:
    image: davarna-bot:pr13-d9434cb10d71
EOF
echo "===== BUILD NETWORK-ISOLATED CODE OVERLAYS ====="
git archive "$SOURCE" -- \
  backend/app/routers/bot_router.py backend/app/routers/finance_router.py \
  backend/app/routers/mini_router.py backend/app/routers/settings_router.py \
  backend/app/static/mini/app.js backend/app/static/mini/index.html \
  backend/app/static/mini/ux-v2.css \
  davarna-bot/bot/keyboards/admin_users.py davarna-bot/bot/keyboards/super_admin.py \
  davarna-bot/bot/routers/admin_users.py davarna-bot/bot/routers/wallet.py | tar -x -C "$TMP"
cat > "$TMP/backend.Dockerfile" <<'EOF'
ARG BASE_IMAGE
FROM $BASE_IMAGE
COPY backend/app/ /app/app/
EOF
cat > "$TMP/bot.Dockerfile" <<'EOF'
ARG BASE_IMAGE
FROM $BASE_IMAGE
COPY davarna-bot/bot/ /app/bot/
EOF
node --check "$TMP/backend/app/static/mini/app.js"
docker build --network none --pull=false -f "$TMP/backend.Dockerfile" --build-arg "BASE_IMAGE=$OLD_BACKEND" -t "$NEW_BACKEND" "$TMP"
docker build --network none --pull=false -f "$TMP/bot.Dockerfile" --build-arg "BASE_IMAGE=$OLD_BOT" -t "$NEW_BOT" "$TMP"
docker run --rm --network none --entrypoint python "$NEW_BACKEND" -m compileall -q \
  /app/app/routers/bot_router.py /app/app/routers/finance_router.py \
  /app/app/routers/mini_router.py /app/app/routers/settings_router.py
docker run --rm --network none --entrypoint python "$NEW_BOT" -m compileall -q \
  /app/bot/routers/wallet.py /app/bot/routers/admin_users.py \
  /app/bot/keyboards/admin_users.py /app/bot/keyboards/super_admin.py
export TAMBOLA_V2_BACKEND_IMAGE="$OLD_BACKEND"
export TAMBOLA_V2_BOT_IMAGE="$OLD_BOT"
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
echo "===== DEPLOY BOT ====="
BOT_STARTED=1
bot_compose "$BACKUP/upgrade.yml" up -d --no-deps --no-build --force-recreate bot
ready=0
for _ in $(seq 1 30); do
  if [[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-bot 2>/dev/null || true)" == healthy ]]; then
    ready=1; break
  fi
  sleep 2
done
(( ready == 1 )) || fail "bot health failed"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$NEW_BACKEND" ]] || fail "backend image mismatch"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == "$NEW_BOT" ]] || fail "bot image mismatch"
echo "===== PR13 DEPLOYED SUCCESSFULLY ====="
docker ps --filter name=davarna-backend --filter name=davarna-bot --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
echo "Protected backup and rollback config: $BACKUP"
