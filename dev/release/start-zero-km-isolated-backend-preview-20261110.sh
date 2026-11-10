#!/usr/bin/env bash
# Zero-km backend preview: connects the exact combined image to the SEPARATE
# persistent MySQL created by prepare-zero-km, on its private Docker network.
# No Telegram bot, no public/private host port, no production secrets,
# no deposits, no auto draw, no autopilot. Does not mutate old production.
set -Eeuo pipefail
umask 077
[[ "${DAVARNA_ZERO_KM_PREVIEW_APPROVAL:-}" == "START_PRIVATE_BACKEND_NO_BOT_NO_PAYMENTS" ]] || {
  echo "BLOCKED: preview-only approval required" >&2; exit 2;
}
[[ "$(id -u)" == 0 ]] || { echo "BLOCKED: root required" >&2; exit 2; }

IMAGE=davarna-backend:zero-km-combined-062cd58647d9
IMAGE_ID=sha256:fc059ab62a9dde6a6f22447607fd13cd12f89cac0a7fd4a2b2949693bdbdccef
DB_CONTAINER=davarna-zero-mysql-20261110
DB_SCHEMA=davarna_zero_20261110
NETWORK=davarna-zero-db-net-20261110
DB_SECRET_FILE=/root/davarna-zero-km-20261110/mysql-secrets.env
REDIS_IMAGE=redis:7-alpine
REDIS_CONTAINER=davarna-zero-redis-preview-20261110
API_CONTAINER=davarna-zero-backend-preview-20261110
EXPECTED_PROD_ID=sha256:4bfe2afa070fa9ca330f70e02ce2233bf2dcf33fb7aa21a1335fc3666cce04e3

die() { echo "BLOCKED: $*" >&2; exit 2; }
[[ "$(docker image inspect -f '{{.Id}}' "$IMAGE")" == "$IMAGE_ID" ]] || die "combined image tag changed"
[[ -r "$DB_SECRET_FILE" ]] || die "private new-DB credentials absent"
[[ "$(stat -c '%a' "$DB_SECRET_FILE")" == "600" ]] || die "new-DB secret file must be mode 600"
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$EXPECTED_PROD_ID" ]] || die "old production backend image changed"
for svc in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$svc")" == healthy ]] || die "existing production unhealthy: $svc"
done
[[ "$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER")" == true ]] || die "zero-km DB unavailable"
[[ "$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}}' "$DB_CONTAINER")" == "$(docker network inspect -f '{{.Id}}' "$NETWORK")" ]] || die "zero-km DB has unexpected network"
[[ "$(docker network inspect -f '{{.Internal}}' "$NETWORK")" == true ]] || die "zero-km network not internal"
docker image inspect "$REDIS_IMAGE" >/dev/null || die "redis image not cached"

if docker container inspect "$REDIS_CONTAINER" >/dev/null 2>&1; then die "preview Redis already exists; no overwrite"; fi
if docker container inspect "$API_CONTAINER" >/dev/null 2>&1; then die "preview API already exists; no overwrite"; fi

# Read ONLY the new, private DB credentials; never inherit the live .env.prod.
set -a
# shellcheck disable=SC1090
source "$DB_SECRET_FILE"
set +a
[[ "${MYSQL_DATABASE:-}" == "$DB_SCHEMA" && "${MYSQL_USER:-}" == davarna_zero_app ]] || die "new DB secrets do not target expected schema"
[[ "${MYSQL_PASSWORD:-}" =~ ^[[:xdigit:]]{64}$ ]] || die "unexpected new DB password format"
DB_URL="mysql+pymysql://${MYSQL_USER}:${MYSQL_PASSWORD}@${DB_CONTAINER}/${DB_SCHEMA}?charset=utf8mb4"
unset MYSQL_ROOT_PASSWORD

echo "===== ZERO-KM DATABASE MUST STILL BE EMPTY ====="
for table in users wallets wallet_txs games game_purchases crypto_deposit_requests deposit_requests withdraw_requests; do
  n="$(docker exec -e MYSQL_PWD="$MYSQL_PASSWORD" "$DB_CONTAINER" mysql -u"$MYSQL_USER" "$DB_SCHEMA" --batch --skip-column-names -e "SELECT COUNT(*) FROM $table;" | tr -d '\r\n')"
  [[ "$n" == 0 ]] || die "unexpected data in new DB: $table ($n)"
done
echo "PASS: new DB still empty"

STARTED_REDIS=0
STARTED_BACKEND=0
finish() {
  rc=$?
  if (( rc != 0 )); then
    echo "FAILED: removing only preview containers" >&2
    if (( STARTED_BACKEND )); then docker rm -f "$API_CONTAINER" >/dev/null 2>&1 || true; fi
    if (( STARTED_REDIS )); then docker rm -f "$REDIS_CONTAINER" >/dev/null 2>&1 || true; fi
  fi
  exit "$rc"
}
trap finish EXIT

echo "===== PRIVATE PREVIEW REDIS (NO PERSISTENT DATA) ====="
docker run -d --name "$REDIS_CONTAINER" --network "$NETWORK" \
  --restart no --memory 128m --memory-swap 128m \
  --security-opt no-new-privileges --cap-drop ALL \
  --tmpfs /data:rw,nosuid,size=64m \
  "$REDIS_IMAGE" redis-server --save '' --appendonly no >/dev/null
STARTED_REDIS=1
READY=0
for _ in $(seq 1 30); do
  if [[ "$(docker exec "$REDIS_CONTAINER" redis-cli ping 2>/dev/null || true)" == PONG ]]; then READY=1; break; fi
  sleep 1
done
[[ "$READY" == 1 ]] || die "preview Redis startup failed"

echo "===== PRIVATE ZERO-KM BACKEND (NO BOT / NO PORTS) ====="
docker run -d --name "$API_CONTAINER" --network "$NETWORK" \
  --restart no --memory 512m --memory-swap 512m \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,size=64m \
  --tmpfs /app/storage/receipts:rw,nosuid,size=32m \
  -e DATABASE_URL="$DB_URL" \
  -e REDIS_URL="redis://$REDIS_CONTAINER:6379/0" \
  -e RECEIPTS_DIR=/app/storage/receipts \
  -e ADMIN_AUTH_ENABLED=true \
  -e AUTH_DEBUG_ENABLED=false \
  -e MINI_SESSION_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  -e CRYPTO_PAYMENTS_ENABLED=false \
  -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
  -e CRYPTO_TRON_USDT_ENABLED=false \
  -e CRYPTO_TON_ENABLED=false \
  -e CRYPTO_DIRECT_WALLET_PAYMENTS_ENABLED=false \
  -e GAME_AUTO_DRAW_ENABLED=false \
  -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
  -e GAME_TAMBOLA_V2_ENABLED=false \
  -e DAVARNA_CRYPTO_ROTATION_PRODUCTION= \
  -e DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL= \
  --entrypoint uvicorn "$IMAGE" app.main:app --host 0.0.0.0 --port 8000 >/dev/null
STARTED_BACKEND=1

echo "===== CHECK API USING PYTHON INSIDE PRIVATE CONTAINER ====="
READY=0
for _ in $(seq 1 45); do
  if docker exec "$API_CONTAINER" python -c 'import urllib.request; assert urllib.request.urlopen("http://127.0.0.1:8000/health/db", timeout=3).read()==b"{\"ok\":true}"' >/dev/null 2>&1; then
    READY=1; break
  fi
  if [[ "$(docker inspect -f '{{.State.Running}}' "$API_CONTAINER" 2>/dev/null || true)" != true ]]; then break; fi
  sleep 2
done
if [[ "$READY" != 1 ]]; then
  echo "===== PREVIEW BACKEND ERROR LOGS ====="
  docker logs --tail 60 "$API_CONTAINER" 2>&1 | sed -E 's#(mysql\\+pymysql://)[^@[:space:]]+@#\\1[REDACTED]@#g' || true
  die "preview backend health not ready"
fi

docker exec -i "$API_CONTAINER" python - <<'PY'
from app.core import config as c
from sqlalchemy.engine import make_url
db=make_url(c.DATABASE_URL)
assert db.database=="davarna_zero_20261110"
assert db.host=="davarna-zero-mysql-20261110"
for flag in ("CRYPTO_PAYMENTS_ENABLED","CRYPTO_AUTO_CONFIRM_ENABLED","GAME_AUTO_DRAW_ENABLED","GAME_AUTOPILOT_RUNTIME_ENABLED"):
    assert not getattr(c,flag), f"{flag} enabled"
print("PASS: preview DB + all workers/payments disabled")
PY
docker exec "$API_CONTAINER" python -c '
import urllib.request, urllib.error
base="http://127.0.0.1:8000"
for path,token in (("/mini/index.html",b"superadmin-workspace-v13"),("/mini/app.js",b"showSuperAdminPanelV13")):
    body=urllib.request.urlopen(base+path,timeout=5).read()
    assert token in body, path
    print("PASS:",path)
try:
    urllib.request.urlopen(base+"/mini-api/admin/ops-dashboard",timeout=5)
except urllib.error.HTTPError as exc:
    assert exc.code in (401,403), "admin API leaked"
    print("PASS: admin API denies anonymous",exc.code)
else:
    raise RuntimeError("anonymous dashboard access unexpectedly allowed")
'

[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$EXPECTED_PROD_ID" ]] || die "production image changed during preview"
[[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-backend)" == healthy ]] || die "production backend health changed"
echo "===== PRIVATE ZERO-KM PREVIEW PASS ====="
echo "BACKEND=$API_CONTAINER"
echo "REDIS=$REDIS_CONTAINER"
echo "DATABASE=$DB_SCHEMA"
echo "EXPOSED_PORTS=none"
echo "BOT_STARTED=false"
echo "PAYMENTS=false"
echo "PRODUCTION_UNCHANGED=true"
echo "NEXT=owner-bootstrap, wallet address configuration, controlled cutover"
