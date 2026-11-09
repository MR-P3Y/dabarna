#!/usr/bin/env bash
# Deploy system-game clock UI and disabled-worker game-start guard onto
# exactly the live backend image; keep automatic draw ON and autopilot OFF.
# Does not create/end games, credit wallets, or manipulate finance records.
set -Eeuo pipefail
umask 077
die(){ echo "BLOCKER: $*" >&2; exit 2; }
ROOT=/opt/davarna-v2
PROD=/opt/davarna
REF="${DAVARNA_AUTO_CLOCK_DEPLOY_REF:?pinned SHA required}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || die "invalid SHA"
[[ "${DAVARNA_AUTO_CLOCK_DEPLOY_APPROVAL:-}" == "DEPLOY_UI_AND_START_GUARD_ONLY" ]] || die "explicit UI deployment approval missing"
[[ "$(id -u)" == 0 ]] || die "root required"
cd "$ROOT"
git cat-file -e "$REF^{commit}" || die "source commit unavailable"
exec 9>/run/davarna-auto-draw-recovery.lock
flock -n 9 || die "another release holds lock"
for svc in davarna-backend davarna-bot davarna-mysql davarna-redis; do
 [[ "$(docker inspect -f '{{.State.Health.Status}}' "$svc")" == "healthy" ]] || die "unhealthy $svc"
done
[[ "$(docker exec davarna-backend python -c 'from app.core import config as c; print(int(c.GAME_AUTO_DRAW_ENABLED),int(c.GAME_AUTOPILOT_RUNTIME_ENABLED))')" == "1 0" ]] || die "draw worker must be enabled, autopilot off"

echo "===== VERIFY 86/87 CLOSED AND NO ACTIVE SYSTEM ROUND ====="
docker exec -i davarna-backend python - <<'PY'
from sqlalchemy import select
from app.core.db import SessionLocal
from app.models.game import Game,GameAutoDraw
with SessionLocal() as db:
 for gid in (86,87):
  game=db.get(Game,gid); control=db.get(GameAutoDraw,gid)
  if not game or not control or str(game.status)!="ENDED" or str(control.status)!="STOPPED":
   raise SystemExit("BLOCKER: previously closed game status drift: "+str(gid))
 active=db.execute(select(Game.id).where(Game.status=="RUNNING",Game.draw_mode=="AUTO")).scalars().all()
 if active: raise SystemExit("BLOCKER: active auto games require independent release procedure: "+str(active))
print("PASS: games 86,87 ended; no active AUTO games")
PY

LIVE_BACKEND_IMAGE="$(docker inspect -f '{{.Config.Image}}' davarna-backend)"
LIVE_BOT_IMAGE="$(docker inspect -f '{{.Config.Image}}' davarna-bot)"
[[ "$(docker image inspect -f '{{.Id}}' "$LIVE_BACKEND_IMAGE")" == "$(docker inspect -f '{{.Image}}' davarna-backend)" ]] || die "backend image byte drift"
[[ "$(docker image inspect -f '{{.Id}}' "$LIVE_BOT_IMAGE")" == "$(docker inspect -f '{{.Image}}' davarna-bot)" ]] || die "bot image byte drift"
export TAMBOLA_V2_BACKEND_IMAGE="$LIVE_BACKEND_IMAGE"
export TAMBOLA_V2_BOT_IMAGE="$LIVE_BOT_IMAGE"
export DAVARNA_UX5_BACKEND_IMAGE="$LIVE_BACKEND_IMAGE"
export DAVARNA_UX5_BOT_IMAGE="$LIVE_BOT_IMAGE"
chain="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' davarna-backend)"
[[ -n "$chain" && "$chain" != "<no value>" ]] || die "missing Compose chain"
IFS=',' read -r -a FILES <<< "$chain"
(( ${#FILES[@]} >= 2 )) || die "unexpected Compose chain"
args=()
for f in "${FILES[@]}"; do
 [[ "$f" = /* && -f "$f" && ! -L "$f" ]] || die "unsafe Compose path"
 args+=(-f "$f")
done
compose(){ (cd "$PROD"; docker compose -p davarna --env-file "$PROD/.env.prod" "${args[@]}" "$@"); }
BACKUP="/root/davarna-v2-release-backups/auto-clock-ui-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p -m 0700 "$BACKUP"
WORK="$(mktemp -d /tmp/davarna-autoclock.XXXXXX)"
RECREATE=0
cleanup() {
 code=$?
 trap - EXIT
 rm -f -- "$BACKUP/before.json" "$BACKUP/after.json"
 rm -rf -- "$WORK"
 if (( code != 0 && RECREATE == 1 )); then
   echo "WARNING: deployment failed; rolling backend image back to previous image" >&2
   compose up -d --no-deps --force-recreate backend || true
 fi
 exit "$code"
}
trap cleanup EXIT

echo "===== ARCHIVE PINNED PATCH FILES ====="
paths=(
 backend/app/services/game_service.py
 backend/app/routers/mini_router.py
 backend/app/static/mini/app.js
 backend/app/static/mini/index.html
 backend/app/static/mini/ux-v2.css
 backend/tests/test_auto_start_worker_disabled_guard.py
)
git archive "$REF" -- "${paths[@]}" | tar -x -C "$WORK"
node --check "$WORK/backend/app/static/mini/app.js" || die "JavaScript syntax invalid"
grep -Fq 'id="adminSystemGameClocks"' "$WORK/backend/app/static/mini/index.html" || die "countdown DOM missing"
python3 - "$WORK" <<'PY'
import ast, pathlib,sys
p=pathlib.Path(sys.argv[1])/"backend"
for name in ("app/services/game_service.py","app/routers/mini_router.py","tests/test_auto_start_worker_disabled_guard.py"):
 ast.parse((p/name).read_text())
print("PASS: Python syntax")
PY
cat >"$WORK/Dockerfile" <<EOF
FROM $LIVE_BACKEND_IMAGE
COPY backend/app/services/game_service.py /app/app/services/game_service.py
COPY backend/app/routers/mini_router.py /app/app/routers/mini_router.py
COPY backend/app/static/mini/app.js /app/app/static/mini/app.js
COPY backend/app/static/mini/index.html /app/app/static/mini/index.html
COPY backend/app/static/mini/ux-v2.css /app/app/static/mini/ux-v2.css
EOF
IMAGE="davarna-backend:auto-clock-${REF:0:12}"
echo "===== BUILD EXACT SOURCE PATCH ON LIVE IMAGE ====="
docker build --pull=false --network none -t "$IMAGE" "$WORK"
echo "===== ISOLATED SAFETY REGRESSION ====="
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
 --tmpfs /tmp:rw,nosuid,size=128m -e RECEIPTS_DIR=/tmp/receipts \
 -e DATABASE_URL=sqlite+pysqlite:///:memory: \
 -e REDIS_URL=redis://127.0.0.1:6379/15 \
 -e GAME_AUTO_DRAW_ENABLED=false \
 -v "$WORK/backend/tests:/app/tests:ro" --entrypoint python "$IMAGE" \
 -m unittest discover -s /app/tests -p test_auto_start_worker_disabled_guard.py -v

echo "===== COMPOSE ONLY BACKEND IMAGE PATCH ====="
overlay="$BACKUP/backend-clock-ui.yml"
printf 'services:\n  backend:\n    image: "%s"\n' "$IMAGE" >"$overlay"
compose config --format json >"$BACKUP/before.json"
compose -f "$overlay" config --format json >"$BACKUP/after.json"
python3 - "$BACKUP/before.json" "$BACKUP/after.json" "$LIVE_BACKEND_IMAGE" "$IMAGE" <<'PY'
import json,sys
a=json.load(open(sys.argv[1]))
b=json.load(open(sys.argv[2]))
if a["services"]["backend"].get("image")!=sys.argv[3]: raise SystemExit("BLOCKER: current Compose backend image drift")
if b["services"]["backend"].get("image")!=sys.argv[4]: raise SystemExit("BLOCKER: new backend image not resolved")
b["services"]["backend"]["image"]=a["services"]["backend"]["image"]
if a!=b: raise SystemExit("BLOCKER: Compose changed something other than backend image")
print("PASS: only backend image changes")
PY
rm -f "$BACKUP/before.json" "$BACKUP/after.json"

echo "===== DEPLOY BACKEND IMAGE, PRESERVE WORKER FLAGS ====="
RECREATE=1
compose -f "$overlay" up -d --no-deps --force-recreate backend
healthy=0
for i in $(seq 1 45); do
 if [[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-backend)" == "healthy" ]]; then healthy=1; break; fi
 sleep 2
done
[[ "$healthy" == 1 ]] || die "backend never became healthy"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$IMAGE" ]] || die "backend image mismatch"
docker exec davarna-backend python -c 'from app.core import config as cfg;assert cfg.GAME_AUTO_DRAW_ENABLED and not cfg.GAME_AUTOPILOT_RUNTIME_ENABLED;print("PASS: worker flags unchanged")'
curl -fsS --max-time 10 http://127.0.0.1:18080/health/db >/dev/null || die "DB health failed"
for path in index.html app.js ux-v2.css; do
 curl -fsS --max-time 10 -o /dev/null "http://127.0.0.1:18080/mini/$path" || die "mini asset missing: $path"
done
curl -fsS --max-time 10 -o "$WORK/deployed-index.html" http://127.0.0.1:18080/mini/index.html || die "index fetch failed"
grep -Fq 'auto-draw-clock-v1' "$WORK/deployed-index.html" || die "new version string not served"
[[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-bot)" == "healthy" ]] || die "bot health drift"
RECREATE=0
echo "===== AUTO CLOCK UI DEPLOY PASS ====="
echo "SOURCE=$REF"
echo "IMAGE=$IMAGE"
echo "ROLLBACK_CONFIG=$BACKUP"
