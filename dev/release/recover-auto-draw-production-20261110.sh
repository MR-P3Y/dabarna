#!/usr/bin/env bash
# ONE-TIME controlled close of stalled #86/#87 + start only the AUTO draw worker.
# Refunds verified card purchases; pays NO prizes; preserves bot and Finance flags.
set -Eeuo pipefail
umask 077
die(){ echo "BLOCKER: $*" >&2; exit 2; }
ROOT=/opt/davarna-v2
PROD=/opt/davarna
REF="${DAVARNA_AUTO_DRAW_RECOVERY_REF:?pinned ref required}"
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || die "bad source ref"
[[ "${DAVARNA_AUTO_DRAW_RECOVERY_APPROVAL:-}" == "CLOSE_86_87_REFUND_PURCHASES_NO_PRIZES_AND_ENABLE_DRAW_WORKER" ]] || die "explicit approval missing"
[[ "$(id -u)" == 0 ]] || die "must run as root"
cd "$ROOT"
git cat-file -e "$REF^{commit}"
echo "===== SYNTAX AND DISABLED-WORKER REGRESSION ====="
git show "$REF:dev/release/close-stalled-auto-86-87-20261110.py" \
  | python3 -c 'import ast,sys; ast.parse(sys.stdin.read()); print("PASS: close script Python syntax")'
TEST_IMAGE=davarna-backend:superadmin-v11-rbac-7101e5c
TEST_ID=sha256:42a77764a254d33f058fb1b606b4a274704975feadce717aa47bb336a3cb9d45
[[ "$(docker image inspect -f '{{.Id}}' "$TEST_IMAGE")" == "$TEST_ID" ]] || die "test image has changed"
WORK="$(mktemp -d /tmp/davarna-autodraw-hotfix.XXXXXX)"
git archive "$REF" -- backend | tar -x -C "$WORK"
node --check "$WORK/backend/app/static/mini/app.js" || die "mini-app JavaScript syntax invalid"
grep -Fq 'id="adminSystemGameClocks"' "$WORK/backend/app/static/mini/index.html" || die "system countdown markup missing"
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,size=128m \
  -e DATABASE_URL=sqlite+pysqlite:///:memory: \
  -e REDIS_URL=redis://127.0.0.1:6379/15 \
  -e RECEIPTS_DIR=/tmp/receipts \
  -e GAME_AUTO_DRAW_ENABLED=false \
  -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
  -v "$WORK/backend:/app:ro" -w /app --entrypoint python "$TEST_IMAGE" \
  -m unittest discover -s tests -p test_auto_start_worker_disabled_guard.py -v
rm -rf -- "$WORK"
for name in davarna-backend davarna-mysql davarna-redis davarna-bot; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$name")" == healthy ]] || die "$name not healthy"
done
[[ "$(docker exec davarna-backend python -c 'from app.core import config as c;print(int(c.GAME_AUTO_DRAW_ENABLED),int(c.GAME_AUTOPILOT_RUNTIME_ENABLED))')" == "0 0" ]] || die "worker flags changed"
exec 9>/run/davarna-auto-draw-recovery.lock
flock -n 9 || die "another game recovery already running"

base_chain="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' davarna-backend)"
[[ -n "$base_chain" && "$base_chain" != "<no value>" ]] || die "compose file labels missing"
IFS=',' read -r -a files <<< "$base_chain"
(( ${#files[@]} >= 2 )) || die "invalid compose file chain"
args=()
for file in "${files[@]}"; do
  [[ "$file" == /* && -f "$file" && ! -L "$file" ]] || die "unsafe compose file path"
  args+=(-f "$file")
done
BACKUP="/root/davarna-v2-release-backups/auto-draw-recovery-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p -m 0700 "$BACKUP"
overlay="$BACKUP/draw-worker-only.yml"
cat >"$overlay" <<'YAML'
services:
  backend:
    environment:
      GAME_AUTO_DRAW_ENABLED: "true"
      GAME_AUTOPILOT_RUNTIME_ENABLED: "false"
YAML
# Compose's immutable-image interpolation is independent from the running
# containers. Populate only the release image substitutions from exact live tags.
LIVE_BACKEND_IMAGE="$(docker inspect -f '{{.Config.Image}}' davarna-backend)"
LIVE_BOT_IMAGE="$(docker inspect -f '{{.Config.Image}}' davarna-bot)"
[[ -n "$LIVE_BACKEND_IMAGE" && -n "$LIVE_BOT_IMAGE" ]] || die "missing deployed image tags"
[[ "$(docker image inspect -f '{{.Id}}' "$LIVE_BACKEND_IMAGE")" == "$(docker inspect -f '{{.Image}}' davarna-backend)" ]] || die "deployed backend tag/image mismatch"
[[ "$(docker image inspect -f '{{.Id}}' "$LIVE_BOT_IMAGE")" == "$(docker inspect -f '{{.Image}}' davarna-bot)" ]] || die "deployed bot tag/image mismatch"
export TAMBOLA_V2_BACKEND_IMAGE="$LIVE_BACKEND_IMAGE"
export TAMBOLA_V2_BOT_IMAGE="$LIVE_BOT_IMAGE"
export DAVARNA_UX5_BACKEND_IMAGE="$LIVE_BACKEND_IMAGE"
export DAVARNA_UX5_BOT_IMAGE="$LIVE_BOT_IMAGE"
compose(){ (cd "$PROD"; docker compose -p davarna --env-file "$PROD/.env.prod" "${args[@]}" "$@"); }
RECREATE_ATTEMPTED=0
recover_backend_on_failure(){
  code=$?
  trap - EXIT
  rm -f -- "$BACKUP/before-config.json" "$BACKUP/after-config.json"
  if (( code != 0 && RECREATE_ATTEMPTED == 1 )); then
    echo "WARNING: auto draw activation incomplete; reverting backend Compose overlay" >&2
    compose up -d --no-deps --force-recreate backend || true
  fi
  exit "$code"
}
trap recover_backend_on_failure EXIT
echo "===== VALIDATE OVERLAY CHANGES ONLY AUTO DRAW FLAG ====="
compose config --format json > "$BACKUP/before-config.json"
compose -f "$overlay" config --format json > "$BACKUP/after-config.json"
python3 - "$BACKUP/before-config.json" "$BACKUP/after-config.json" <<'PY'
import copy,json,sys
before=json.load(open(sys.argv[1]))
after=json.load(open(sys.argv[2]))
import subprocess
live=json.loads(subprocess.check_output(["docker","inspect","davarna-backend"],text=True))[0]
live_image=live["Config"]["Image"]
baseline_image=before["services"]["backend"].get("image")
if baseline_image != live_image:
    raise SystemExit("BLOCKER: Compose image does not match current deployed backend image")
if after["services"]["backend"].get("image") != live_image:
    raise SystemExit("BLOCKER: proposed overlay changes backend image")
a=after["services"]["backend"]["environment"]
b=before["services"]["backend"]["environment"]
if str(b.get("GAME_AUTO_DRAW_ENABLED","")).lower() not in ("false","0"):
    raise SystemExit("BLOCKER: preflight flag mismatch")
if str(b.get("GAME_AUTOPILOT_RUNTIME_ENABLED","")).lower() not in ("false","0"):
    raise SystemExit("BLOCKER: autopilot must stay off")
if a.get("GAME_AUTO_DRAW_ENABLED") not in ("true",True):
    raise SystemExit("BLOCKER: auto flag override ineffective")
if a.get("GAME_AUTOPILOT_RUNTIME_ENABLED") not in ("false",False):
    raise SystemExit("BLOCKER: autopilot unexpectedly enabled")
a["GAME_AUTO_DRAW_ENABLED"]=b["GAME_AUTO_DRAW_ENABLED"]
a["GAME_AUTOPILOT_RUNTIME_ENABLED"]=b["GAME_AUTOPILOT_RUNTIME_ENABLED"]
if before!=after:
    raise SystemExit("BLOCKER: non-flag Compose changes detected")
print("PASS: resulting Compose config changes only GAME_AUTO_DRAW_ENABLED")
PY
rm -f "$BACKUP/before-config.json" "$BACKUP/after-config.json"
echo "===== BACKUP PRODUCTION DB BEFORE COMPENSATED REFUNDS ====="
docker exec davarna-mysql sh -lc '
  MYSQL_PWD="$MYSQL_PASSWORD" exec mysqldump -u"$MYSQL_USER" \
    --single-transaction --quick --triggers "$MYSQL_DATABASE"
' | gzip -1 > "$BACKUP/mysql-before.sql.gz"
[[ -s "$BACKUP/mysql-before.sql.gz" ]] || die "backup missing"
gzip -t "$BACKUP/mysql-before.sql.gz"
chmod 0600 "$BACKUP/mysql-before.sql.gz"
echo "BACKUP=$BACKUP"
echo "===== ATOMIC CLOSE 86/87 + REFUND PURCHASES; NO PRIZES ====="
git show "$REF:dev/release/close-stalled-auto-86-87-20261110.py" \
 | docker exec -i -e DAVARNA_STALLED_AUTO_CLOSE_APPROVAL=CLOSE_86_87_REFUND_PURCHASES_NO_PRIZES \
     davarna-backend python -
echo "===== RECREATE ONLY BACKEND WITH AUTO DRAW WORKER ENABLED ====="
RECREATE_ATTEMPTED=1
compose -f "$overlay" up -d --no-deps --force-recreate backend
echo "===== CHECK BACKEND HEALTH AND FLAGS ====="
healthy=0
for _ in $(seq 1 45); do
 if [[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-backend)" == "healthy" ]]; then healthy=1; break; fi
 sleep 2
done
[[ "$healthy" == 1 ]] || die "backend unhealthy; do not start games; rollback override using saved backup metadata"
docker exec davarna-backend python -c '
from app.core import config as c
assert c.GAME_AUTO_DRAW_ENABLED and not c.GAME_AUTOPILOT_RUNTIME_ENABLED
print("PASS: draw worker enabled, autopilot disabled")
'
docker exec -i davarna-backend python - <<'PY'
from app.core.db import SessionLocal
from app.models.game import Game,GameAutoDraw
from sqlalchemy import select
with SessionLocal() as db:
 for gid in (86,87):
  g=db.get(Game,gid); c=db.get(GameAutoDraw,gid)
  assert g and c and str(g.status)=="ENDED" and str(c.status)=="STOPPED",gid
 remaining=db.execute(select(Game.id).where(Game.status=="RUNNING",Game.draw_mode=="AUTO")).scalars().all()
 assert not remaining,remaining
print("PASS: stalled games closed; no inherited RUNNING AUTO games")
PY
echo "===== RECOVERY SUCCESS ====="
echo "BACKUP=$BACKUP"
