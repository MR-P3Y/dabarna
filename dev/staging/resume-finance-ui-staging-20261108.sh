#!/usr/bin/env bash
# Resume only the isolated finance Staging after seed.py import failure.
# Does not read Production database or secrets, does not change Production.
set -Eeuo pipefail
umask 077
[[ "$(id -u)" == 0 ]] || { echo "BLOCKER: root required"; exit 2; }
[[ "${DAVARNA_FINANCE_UI_STAGE_APPROVAL:-}" == "ISOLATED_UI_ONLY" ]] || { echo "BLOCKER: explicit staging opt-in required"; exit 2; }
ROOT=/opt/davarna-v2
DIR=/opt/davarna-finance-ui-staging
IMAGE=davarna-backend:forum-mini-e7517922-stage2
IMAGE_ID=sha256:b6d2709c3f78ce946a90aeb1b2bd6774acfa6b72a88cd604c370842cc3824850
NET=davarna-finance-ui-isolated
CACHE=davarna-finance-ui-redis
API=davarna-finance-ui-api
die(){ echo "BLOCKER: $*" >&2; exit 2; }
cd "$ROOT"
[[ -f "$DIR/seed.py" && -f "$DIR/backend/app/main.py" && -d "$DIR/data" ]] || die "expected isolated staging files absent"
[[ "$(docker image inspect -f '{{.Id}}' "$IMAGE")" == "$IMAGE_ID" ]] || die "pinned image mismatch"
docker network inspect "$NET" >/dev/null || die "isolated staging network missing"
[[ "$(docker network inspect -f '{{.Internal}}' "$NET")" == "true" ]] || die "staging network not internal"
echo "===== REPAIR FAILED STAGING REDIS ONLY ====="
[[ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$CACHE")" == "$NET" ]] || die "isolated Redis on unexpected network"
[[ "$(docker inspect -f '{{.Config.Image}}' "$CACHE")" == 'redis:7-alpine' ]] || die "unexpected staging Redis image"
if [[ "$(docker inspect -f '{{.State.Status}}' "$CACHE")" == "exited" ]]; then
  [[ "$(docker inspect -f '{{.State.ExitCode}}' "$CACHE")" == "1" ]] || die "unexpected Redis exit code"
  docker logs "$CACHE" 2>&1 | grep -Fq 'chown: .: Operation not permitted' || die "Redis failed for another reason"
  docker rm "$CACHE" >/dev/null
  docker run -d --name "$CACHE" --network "$NET" --restart no \
    --memory 64m --cpus 0.25 --pids-limit 64 --read-only --cap-drop ALL \
    --security-opt no-new-privileges --user 999:999 \
    --tmpfs /tmp:rw,nosuid,nodev,mode=1777 \
    --entrypoint redis-server redis:7-alpine \
    --save '' --appendonly no --dir /tmp >/dev/null
fi
[[ "$(docker inspect -f '{{.State.Running}}' "$CACHE")" == "true" ]] || die "isolated Redis not running"
[[ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$CACHE")" == "$NET" ]] || die "isolated Redis network changed"

! docker container inspect "$API" >/dev/null 2>&1 || die "staging API container already exists; investigate"
! ss -lnt | grep -qE '127[.]0[.]0[.]1:18083[[:space:]]' || die "port 18083 occupied"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
 [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || die "Production dependency unhealthy: $c"
done
echo "===== PREPARE SQLITE-SAFE SYNTHETIC SEED ====="
# SQLite index names are global; MySQL permits the same index name on different tables.
# Keep the application models unchanged; rename only colliding staging indexes at DDL time.
python3 - "$DIR/seed.py" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
s=p.read_text(encoding="utf-8")
needle="Base.metadata.create_all(engine)"
replacement="""# SQLite-only DDL workaround for repeated MySQL index names.
seen=set()
for table in Base.metadata.sorted_tables:
    for idx in sorted(table.indexes, key=lambda i: (str(i.name), table.name)):
        if idx.name in seen:
            idx.name = f"staging_{table.name}_{idx.name}"
        seen.add(idx.name)
Base.metadata.create_all(engine)"""
if s.count(needle)!=1:
    raise SystemExit("BLOCKER: unexpected synthetic seed code")
p.write_text(s.replace(needle,replacement),encoding="utf-8")
PY
# The failed first attempt may have partially created staging.sqlite. Never alter it.
# Use a dedicated fresh SQLite filename for the corrected DDL.
[[ ! -e "$DIR/data/staging-v2.sqlite" ]] || die "corrected staging DB already exists; inspect before retry"
COMMON=(--network "$NET" --read-only --cap-drop ALL \
  --security-opt no-new-privileges --memory 384m --cpus 0.75 --pids-limit 128 \
  --tmpfs /tmp:rw,nosuid,nodev --tmpfs /run:rw,nosuid,nodev \
  -v "$DIR/backend:/app:ro" -v "$DIR/data:/data:rw" \
  -e PYTHONPATH=/app \
  -e DATABASE_URL=sqlite:////data/staging-v2.sqlite \
  -e "REDIS_URL=redis://$CACHE:6379/0" \
  -e TELEGRAM_BOT_TOKEN=000000000:STAGING_ONLY \
  -e MINI_SESSION_SECRET=LOCAL_STAGING_ONLY_NOT_FOR_PRODUCTION_20261108 \
  -e RBAC_OWNER_USER_ID=91001 \
  -e SUPER_ADMIN_TG_USER_IDS=990000000001 \
  -e ADMIN_AUTH_ENABLED=true \
  -e GAME_TAMBOLA_V2_ENABLED=false \
  -e GAME_AUTO_DRAW_ENABLED=false \
  -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
  -e CRYPTO_PAYMENTS_ENABLED=false \
  -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
  -e RECEIPTS_DIR=/tmp/receipts \
  -e PYTHONDONTWRITEBYTECODE=1 -w /app)
echo "===== SEED SYNTHETIC DATABASE ====="
[[ ! -e "$DIR/data/preview-session.json" ]] || die "staging session exists; refusing to overwrite"
docker run --rm "${COMMON[@]}" -v "$DIR/seed.py:/tmp/seed.py:ro" \
 --entrypoint python "$IMAGE" /tmp/seed.py
echo "===== INJECT SYNTHETIC SESSION INTO ISOLATED HTML ====="
python3 - "$DIR/backend/app/static/mini/index.html" "$DIR/data/preview-session.json" <<'PY'
from pathlib import Path
import json,sys
html=Path(sys.argv[1])
payload=json.loads(Path(sys.argv[2]).read_text())
text=html.read_text(encoding="utf-8")
if text.count("</head>")!=1 or "sessionStorage.setItem('davarna_mini_session_v1'" in text:
    raise SystemExit("BLOCKER: invalid or previously modified staging HTML")
script="<script>sessionStorage.setItem('davarna_mini_session_v1',"+json.dumps(json.dumps(payload,separators=(',',':')))+");</script>"
html.write_text(text.replace("</head>",script+"\n</head>"),encoding="utf-8")
PY
echo "===== START ISOLATED BACKEND ====="
docker run -d --name "$API" --restart no "${COMMON[@]}" \
 -p 127.0.0.1:18083:8000 --entrypoint uvicorn "$IMAGE" \
 app.main:app --host 0.0.0.0 --port 8000 >/dev/null
for i in $(seq 1 15); do
 if curl -fsS --max-time 3 http://127.0.0.1:18083/health/db >/dev/null 2>&1; then break; fi
 sleep 1
done
curl -fsS --max-time 5 http://127.0.0.1:18083/health/db || die "staging DB health failed; check docker logs $API"
curl -fsS --max-time 5 -o /dev/null http://127.0.0.1:18083/mini/index.html || die "staging HTML missing"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
 [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || die "Production unhealthy after isolated stage"
done
echo "PASS: ISOLATED STAGING STARTED on http://127.0.0.1:18083/mini/index.html"
