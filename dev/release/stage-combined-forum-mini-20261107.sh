#!/usr/bin/env bash
# BUILD + TEST ONLY. Does not recreate production containers, alter DB/schema,
# enable payment/Autopilot flags, post Telegram messages, or change Compose files.
set -Eeuo pipefail
umask 077

ROOT=/opt/davarna-v2
PROD=/opt/davarna
BASE_SOURCE=e087c40bd4714dbc703e48d7bc1f24bd9c35d9aa
SOURCE=e7517922f08685be99a8f55564da1ad22abeddac
OLD_BACKEND=davarna-backend:rbac-pr14-e087c40bd471
OLD_BOT=davarna-bot:pr13-d9434cb10d71
NEW_BACKEND=davarna-backend:forum-mini-e7517922
NEW_BOT=davarna-bot:forum-mini-e7517922
COMPOSE_BASE=$PROD/docker-compose.yml
INACTIVE=$ROOT/deploy/tambola-v2-inactive.compose.yml
MANUAL=/root/davarna-v2-release-backups/tambola-v2-manual.compose.yml
UX5=$ROOT/dev/release/ux5-candidate.compose.yml
PR13=/root/davarna-v2-release-backups/pr13-d9434cb10d71-20261106T183004Z/upgrade.yml
PR14=/root/davarna-v2-release-backups/rbac-pr14-e087c40bd471-20261106T193945Z/upgrade.yml

fail() { echo "BLOCKER: $*" >&2; exit 2; }
TMP=""
finish() {
  local rc=$?
  trap - EXIT
  if [[ -n "$TMP" && -d "$TMP" ]]; then rm -rf -- "$TMP"; fi
  exit "$rc"
}
trap finish EXIT

[[ "$(id -u)" == 0 ]] || fail "root required"
cd "$ROOT"
git cat-file -e "$SOURCE^{commit}" || fail "merged source commit unavailable"
git merge-base --is-ancestor "$SOURCE" origin/feature/ui-ux-refresh-tambola-v2-20261106 || fail "unexpected source lineage"
git merge-base --is-ancestor "$BASE_SOURCE" "$SOURCE" || fail "PR14 baseline is not ancestor"
for image in "$OLD_BACKEND" "$OLD_BOT"; do
  docker image inspect "$image" >/dev/null || fail "missing base image $image"
done
for image in "$NEW_BACKEND" "$NEW_BOT"; do
  if docker image inspect "$image" >/dev/null 2>&1; then
    fail "candidate tag already exists; do not overwrite: $image"
  fi
done
for file in "$COMPOSE_BASE" "$INACTIVE" "$MANUAL" "$PR13" "$PR14" "$PROD/.env.prod" "$PROD/davarna-bot/.env.prod"; do
  [[ -f "$file" ]] || fail "missing critical Compose or environment file: $file"
done
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || fail "$c not healthy"
done
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$OLD_BACKEND" ]] || fail "backend image changed since 45 passing tests"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == "$OLD_BOT" ]] || fail "Bot image changed since 45 passing tests"
[[ "$(curl -fsS --max-time 8 http://127.0.0.1:18080/health/db)" == '{"ok":true}' ]] || fail "backend DB health failed"

# Exact original image-only overlays; fail if any stored release YAML was edited.
printf '%s\n' services: '  backend:' '    image: davarna-backend:pr13-d9434cb10d71' \
  '  bot:' '    image: davarna-bot:pr13-d9434cb10d71' | cmp -s - "$PR13" || fail "PR13 overlay content modified"
printf '%s\n' services: '  backend:' '    image: davarna-backend:rbac-pr14-e087c40bd471' \
  '  bot:' '    image: davarna-bot:pr13-d9434cb10d71' | cmp -s - "$PR14" || fail "PR14 overlay content modified"

load_chain() {
  local container="$1" result_array="$2" csv file
  csv="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$container")" || fail "$container labels unavailable"
  [[ -n "$csv" && "$csv" != "<no value>" ]] || fail "$container Compose chain missing"
  local -a files=()
  IFS=',' read -r -a files <<< "$csv"
  (( ${#files[@]} >= 2 )) || fail "$container Compose chain too short"
  [[ "${files[0]}" == "$COMPOSE_BASE" && "${files[1]}" == "$INACTIVE" ]] || fail "$container Compose base order changed"
  local found13=0 found14=0 foundmanual=0
  local -A seen=()
  for file in "${files[@]}"; do
    [[ "$file" == /* && -f "$file" ]] || fail "$container has unavailable file: $file"
    [[ -z "${seen[$file]+present}" ]] || fail "$container duplicate Compose layer"
    seen[$file]=1
    case "$file" in
      "$COMPOSE_BASE"|"$INACTIVE"|"$UX5") ;;
      "$MANUAL") foundmanual=$((foundmanual+1));;
      "$PR13") found13=$((found13+1));;
      "$PR14") found14=$((found14+1));;
      *) fail "$container unrecognized Compose layer: $file";;
    esac
  done
  (( found13==1 )) || fail "$container missing PR13 overlay"
  if [[ "$container" == davarna-backend ]]; then
    (( foundmanual==1 && found14==1 )) || fail "backend expected manual/PR14 layers"
    [[ "${files[$((${#files[@]}-1))]}" == "$PR14" ]] || fail "backend last layer not PR14"
  else
    (( foundmanual==0 && found14==0 )) || fail "Bot contains backend-only layer"
    [[ "${files[$((${#files[@]}-1))]}" == "$PR13" ]] || fail "Bot last layer not PR13"
  fi
  local -n array_ref="$result_array"
  array_ref=("${files[@]}")
  echo "PASS: $container Compose chain recognized"
}
declare -a BACK_FILES=() BOT_FILES=()
load_chain davarna-backend BACK_FILES
load_chain davarna-bot BOT_FILES

expected="$(printf '%s\n' \
  backend/app/routers/mini_router.py \
  backend/app/services/deposit_destination_admin.py \
  backend/app/static/mini/app.js \
  backend/app/static/mini/index.html \
  backend/app/static/mini/ux-v2.css \
  davarna-bot/bot/main.py \
  davarna-bot/bot/routers/help.py \
  davarna-bot/bot/routers/menu.py \
  davarna-bot/bot/routers/start.py \
  davarna-bot/bot/services/user_forum_navigation.py \
  davarna-bot/bot/services/user_topics.py \
  davarna-bot/bot/workers/notifier.py | sort)"
actual="$(git diff --name-only "$BASE_SOURCE" "$SOURCE" -- backend/app davarna-bot/bot | sort)"
[[ "$actual" == "$expected" ]] || {
  echo "Unexpected runtime source differences since PR14:" >&2
  git diff --name-only "$BASE_SOURCE" "$SOURCE" -- backend/app davarna-bot/bot >&2
  fail "runtime file allowlist mismatch"
}
echo "PASS: 12 exact reviewed runtime files"

available=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
(( available > 650 * 1024 )) || fail "less than 650 MiB available RAM"
(( $(df -Pk "$PROD" | awk 'NR==2 {print $4}') > 3 * 1024 * 1024 )) || fail "less than 3 GiB available disk"
command -v node >/dev/null || fail "node command missing"

TMP=$(mktemp -d /tmp/davarna-forum-mini-stage.XXXXXX)
chmod 0700 "$TMP"
git archive "$SOURCE" -- \
  backend/app/routers/mini_router.py \
  backend/app/services/deposit_destination_admin.py \
  backend/app/static/mini/app.js \
  backend/app/static/mini/index.html \
  backend/app/static/mini/ux-v2.css \
  backend/tests/test_mini_superadmin_bank_admin.py \
  backend/tests/test_mini_superadmin_ui_contract.py \
  backend/tests/test_user_forum_created_notice.py \
  backend/tests/mysql_super_bank_admin_e2e.py \
  davarna-bot/bot/main.py \
  davarna-bot/bot/routers/help.py \
  davarna-bot/bot/routers/menu.py \
  davarna-bot/bot/routers/start.py \
  davarna-bot/bot/services/user_forum_navigation.py \
  davarna-bot/bot/services/user_topics.py \
  davarna-bot/bot/workers/notifier.py \
  davarna-bot/tests | tar -x -C "$TMP"

echo "===== SYNTAX AND CANDIDATE IMAGE BUILD (NETWORK NONE) ====="
node --check "$TMP/backend/app/static/mini/app.js"
cat > "$TMP/backend.Dockerfile" <<'EOF'
ARG BASE_IMAGE
FROM $BASE_IMAGE
COPY backend/app/routers/mini_router.py /app/app/routers/mini_router.py
COPY backend/app/services/deposit_destination_admin.py /app/app/services/deposit_destination_admin.py
COPY backend/app/static/mini/app.js /app/app/static/mini/app.js
COPY backend/app/static/mini/index.html /app/app/static/mini/index.html
COPY backend/app/static/mini/ux-v2.css /app/app/static/mini/ux-v2.css
EOF
cat > "$TMP/bot.Dockerfile" <<'EOF'
ARG BASE_IMAGE
FROM $BASE_IMAGE
COPY davarna-bot/bot/main.py /app/bot/main.py
COPY davarna-bot/bot/routers/help.py /app/bot/routers/help.py
COPY davarna-bot/bot/routers/menu.py /app/bot/routers/menu.py
COPY davarna-bot/bot/routers/start.py /app/bot/routers/start.py
COPY davarna-bot/bot/services/user_forum_navigation.py /app/bot/services/user_forum_navigation.py
COPY davarna-bot/bot/services/user_topics.py /app/bot/services/user_topics.py
COPY davarna-bot/bot/workers/notifier.py /app/bot/workers/notifier.py
EOF
docker build --network none --pull=false -f "$TMP/backend.Dockerfile" --build-arg "BASE_IMAGE=$OLD_BACKEND" -t "$NEW_BACKEND" "$TMP"
docker build --network none --pull=false -f "$TMP/bot.Dockerfile" --build-arg "BASE_IMAGE=$OLD_BOT" -t "$NEW_BOT" "$TMP"

echo "===== TEST BUILT BOT IMAGE, NO NETWORK ====="
docker run --rm --network none --read-only --memory 512m --cpus 1 \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
  -v "$TMP/davarna-bot/tests:/offline-tests:ro" \
  -e TELEGRAM_BOT_TOKEN='123456789:TEST_ONLY' -e PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python -w /app "$NEW_BOT" \
  -m unittest discover -s /offline-tests -p 'test_*.py' -v

echo "===== TEST BUILT BACKEND IMAGE, NO NETWORK ====="
for pattern in 'test_mini_superadmin_*.py' test_user_forum_created_notice.py; do
  docker run --rm --network none --read-only --memory 512m --cpus 1 \
    --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
    -v "$TMP/backend/tests:/offline-tests:ro" \
    -e DATABASE_URL='sqlite+pysqlite:///:memory:' -e REDIS_URL='redis://127.0.0.1:6379/0' \
    -e RECEIPTS_DIR=/tmp/receipts -e PYTHONDONTWRITEBYTECODE=1 \
    --entrypoint python -w /app "$NEW_BACKEND" \
    -m unittest discover -s /offline-tests -p "$pattern" -v
done

echo "===== PRIVATE TEST DB CREDENTIALS ====="
python3 - "$TMP/test-env" <<'PY'
import json, os, subprocess, sys
obj=json.loads(subprocess.check_output(["docker","inspect","davarna-backend"],text=True))[0]
env=dict(x.split("=",1) for x in obj["Config"]["Env"] if "=" in x)
url=env.get("DATABASE_URL")
if not url: raise SystemExit("BLOCKER: backend DATABASE_URL absent")
with open(sys.argv[1],"w",encoding="utf-8") as f:
    f.write("DATABASE_URL=" + json.dumps(url) + "\n")
os.chmod(sys.argv[1],0o600)
PY
echo "===== TEST BUILT BACKEND MYSQL E2E, ISOLATED DB ONLY ====="
docker run --rm --network davarna_default --read-only --memory 512m --cpus 1 \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
  -v "$TMP/backend/tests:/offline-tests:ro" -v "$TMP/test-env:/run/secrets/davarna_env:ro" \
  -e DAVARNA_SUPER_BANK_TEST_DB='davarna_tambola_v2_test_20261104' \
  -e RECEIPTS_DIR=/tmp/receipts -e PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python -w /app "$NEW_BACKEND" \
  -m unittest discover -s /offline-tests -p mysql_super_bank_admin_e2e.py -v

echo "===== RENDER CANDIDATE COMPOSE (READ-ONLY) ====="
cat > "$TMP/candidate.yml" <<'EOF'
services:
  backend:
    image: davarna-backend:forum-mini-e7517922
  bot:
    image: davarna-bot:forum-mini-e7517922
EOF
declare -a backend_args=() bot_args=()
for f in "${BACK_FILES[@]}"; do backend_args+=(-f "$f"); done
for f in "${BOT_FILES[@]}"; do bot_args+=(-f "$f"); done
export TAMBOLA_V2_BACKEND_IMAGE="$OLD_BACKEND"
export TAMBOLA_V2_BOT_IMAGE="$OLD_BOT"
export DAVARNA_UX5_BACKEND_IMAGE="$OLD_BACKEND"
export DAVARNA_UX5_BOT_IMAGE="$OLD_BOT"
(cd "$PROD"; docker compose -p davarna --env-file "$PROD/.env.prod" \
  "${backend_args[@]}" -f "$TMP/candidate.yml" config --format json) > "$TMP/backend.json"
(cd "$PROD"; docker compose -p davarna --env-file "$PROD/.env.prod" \
  "${bot_args[@]}" -f "$TMP/candidate.yml" config --format json) > "$TMP/bot.json"
python3 - "$TMP/backend.json" "$TMP/bot.json" "$NEW_BACKEND" "$NEW_BOT" <<'PY'
import json, subprocess, sys
def data(container):
    return json.loads(subprocess.check_output(["docker","inspect",container],text=True))[0]
def img(tag):
    return json.loads(subprocess.check_output(["docker","image","inspect",tag],text=True))[0]
def envmap(rows):
    return {x.split("=",1)[0]:x.split("=",1)[1] for x in rows if "=" in x}
for name, configpath, tag in (
    ("backend",sys.argv[1],sys.argv[3]),
    ("bot",sys.argv[2],sys.argv[4]),
):
    live=data("davarna-"+name)
    cfg=json.load(open(configpath,encoding="utf-8"))["services"][name]
    if cfg.get("image")!=tag:
        raise SystemExit("BLOCKER: candidate image override mismatch for "+name)
    effective=envmap(img(tag)["Config"].get("Env") or [])
    for k,v in (cfg.get("environment") or {}).items():
        if v is None: effective.pop(k,None)
        else: effective[k]=str(v)
    if effective!=envmap(live["Config"].get("Env") or []):
        raise SystemExit("BLOCKER: effective environment differs for "+name)
    liveports={(p,b.get("HostIp") or "0.0.0.0",str(b.get("HostPort") or ""))
        for p,bs in (live["HostConfig"].get("PortBindings") or {}).items() for b in bs or []}
    newports={(str(p["target"])+"/"+str(p.get("protocol") or "tcp"),
               str(p.get("host_ip") or "0.0.0.0"),str(p["published"]))
        for p in cfg.get("ports") or []}
    if liveports!=newports:
        raise SystemExit("BLOCKER: published ports differ for "+name)
    oldmounts={(v.get("Type"),v.get("Source"),v.get("Destination"),not v.get("RW",True))
               for v in live.get("Mounts") or []}
    newmounts={(v.get("type"),v.get("source"),v.get("target"),bool(v.get("read_only",False)))
               for v in cfg.get("volumes") or []}
    if oldmounts!=newmounts:
        raise SystemExit("BLOCKER: volume mounts differ for "+name)
    print("PASS: "+name+" candidate is image-only, same environment/ports/volumes")
PY

echo "===== HEALTHY PRODUCTION UNCHANGED ====="
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$OLD_BACKEND" ]] || fail "production backend image changed"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == "$OLD_BOT" ]] || fail "production Bot image changed"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || fail "production unhealthy after staging: $c"
done
echo "===== CANDIDATE STAGED & VERIFIED, NOTHING DEPLOYED ====="
docker image inspect --format 'BACKEND_CANDIDATE={{.Id}}' "$NEW_BACKEND"
docker image inspect --format 'BOT_CANDIDATE={{.Id}}' "$NEW_BOT"
