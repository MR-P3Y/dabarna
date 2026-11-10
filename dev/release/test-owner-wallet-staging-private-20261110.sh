#!/usr/bin/env bash
# Private, no-money/no-bot end-to-end HTTP smoke for owner-managed wallets.
# Reuses the pre-existing ZERO-KM DB and Redis; no wallet address changes.
# Temporarily pauses ONLY the older private preview API to reduce memory use.
# Stops the new test API and restores the previous private preview on exit.
set -Eeuo pipefail
umask 077

[[ "${DAVARNA_OWNER_WALLET_STAGE_APPROVAL:-}" == "TEST_PRIVATE_API_NO_MONEY_NO_BOT" ]] || {
  echo "BLOCKED: staging test approval is required" >&2; exit 2;
}
[[ "$(id -u)" == 0 ]] || { echo "BLOCKED: root required" >&2; exit 2; }
die(){ echo "BLOCKED: $*" >&2; exit 2; }

BACKEND_IMAGE=davarna-backend:owner-wallet-v13-4b4de7d73b3e
BACKEND_ID=sha256:95f75be4aea80fba19890281be89bab18744ff4c76fc9c76a1cdfc28bff4c107
BOT_IMAGE=davarna-bot:owner-wallet-4b4de7d73b3e
BOT_ID=sha256:1148b7b3f8ace313f17b1481c1cbd99614c60f53e4771b4d5b3428c453b15fc5
PREVIEW_OLD=davarna-zero-backend-preview-20261110
PREVIEW_OLD_ID=sha256:fc059ab62a9dde6a6f22447607fd13cd12f89cac0a7fd4a2b2949693bdbdccef
PREVIEW_TEST=davarna-owner-wallet-private-api-test-20261110
DB_CONTAINER=davarna-zero-mysql-20261110
DB_SCHEMA=davarna_zero_20261110
REDIS_CONTAINER=davarna-zero-redis-preview-20261110
NETWORK=davarna-zero-db-net-20261110
SECRETS=/root/davarna-zero-km-20261110/mysql-secrets.env

echo "===== CHECK PRECONDITIONS / NO PRODUCTION MODIFICATION ====="
[[ "$(docker image inspect -f '{{.Id}}' "$BACKEND_IMAGE")" == "$BACKEND_ID" ]] || die "backend image mismatch"
[[ "$(docker image inspect -f '{{.Id}}' "$BOT_IMAGE")" == "$BOT_ID" ]] || die "bot image mismatch"
[[ "$(docker inspect -f '{{.Image}}' "$PREVIEW_OLD")" == "$PREVIEW_OLD_ID" ]] || die "old private preview image changed"
[[ "$(docker inspect -f '{{.State.Running}}' "$PREVIEW_OLD")" == true ]] || die "older private preview API is not running"
[[ "$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER")" == true ]] || die "isolated MySQL missing"
[[ "$(docker inspect -f '{{.State.Running}}' "$REDIS_CONTAINER")" == true ]] || die "isolated Redis missing"
[[ "$(docker network inspect -f '{{.Internal}}' "$NETWORK")" == true ]] || die "private Docker network not internal"
[[ "$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}}' "$DB_CONTAINER")" == "$(docker network inspect -f '{{.Id}}' "$NETWORK")" ]] || die "private DB is not isolated"
[[ "$(stat -c '%a' "$SECRETS")" == 600 ]] || die "new DB secrets file permissions changed"
if docker container inspect "$PREVIEW_TEST" >/dev/null 2>&1; then die "test container name already in use"; fi

PROD_API="$(docker inspect -f '{{.Image}}' davarna-backend)"
PROD_BOT="$(docker inspect -f '{{.Image}}' davarna-bot)"
PROD_MYSQL="$(docker inspect -f '{{.Image}}' davarna-mysql)"
for svc in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$svc")" == healthy ]] || die "live service unhealthy: $svc"
done

# Read ONLY fresh-database secrets. No .env.prod, original financial DB or bot token.
set -a
# shellcheck disable=SC1090
source "$SECRETS"
set +a
[[ "${MYSQL_DATABASE:-}" == "$DB_SCHEMA" && "${MYSQL_USER:-}" == davarna_zero_app ]] || die "unexpected isolated DB credentials"
[[ "${MYSQL_PASSWORD:-}" =~ ^[[:xdigit:]]{64}$ ]] || die "unexpected isolated DB password format"
URL="mysql+pymysql://${MYSQL_USER}:${MYSQL_PASSWORD}@${DB_CONTAINER}/${DB_SCHEMA}?charset=utf8mb4"
unset MYSQL_ROOT_PASSWORD

echo "===== ISOLATED OWNER / FINANCIAL DATA CHECK ====="
sql(){ docker exec -e MYSQL_PWD="$MYSQL_PASSWORD" "$DB_CONTAINER" mysql -u"$MYSQL_USER" "$DB_SCHEMA" --batch --skip-column-names -e "$1" | tr -d '\r\n'; }
[[ "$(sql 'SELECT COUNT(*) FROM users')" == 1 ]] || die "new DB owner count not one"
[[ "$(sql 'SELECT COUNT(*) FROM users WHERE id=1')" == 1 ]] || die "new DB owner ID not one"
[[ "$(sql "SELECT COUNT(*) FROM user_roles ur JOIN roles r ON ur.role_id=r.id WHERE ur.user_id=1 AND r.name='SUPER_ADMIN'")" == 1 ]] || die "fresh owner role missing"
for table in wallets wallet_txs games game_purchases crypto_deposit_requests deposit_requests withdraw_requests; do
  [[ "$(sql "SELECT COUNT(*) FROM $table")" == 0 ]] || die "nonzero fresh $table"
done
echo "PASS: only owner identity exists; no fresh financial records"

OLD_STOPPED=0
TEST_CREATED=0
finish(){
  result=$?
  trap - EXIT INT TERM
  if (( TEST_CREATED )); then docker rm -f "$PREVIEW_TEST" >/dev/null 2>&1 || true; fi
  if (( OLD_STOPPED )); then
    if docker start "$PREVIEW_OLD" >/dev/null 2>&1; then
      echo "PASS: older PRIVATE preview restored"
    else
      echo "WARNING: failed to restart older PRIVATE preview; production remains unaffected" >&2
      result=7
    fi
  fi
  exit "$result"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "===== PAUSE ONLY THE OLD PRIVATE PREVIEW, NOT PRODUCTION ====="
docker stop -t 10 "$PREVIEW_OLD" >/dev/null
OLD_STOPPED=1

echo "===== START REPLACEMENT PRIVATE BACKEND WITH ALL MONEY/WORKERS OFF ====="
docker run -d --name "$PREVIEW_TEST" --network "$NETWORK" \
  --restart no --memory=512m --memory-swap=512m \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,size=64m \
  --tmpfs /app/storage/receipts:rw,nosuid,size=32m \
  -e DATABASE_URL="$URL" \
  -e REDIS_URL="redis://$REDIS_CONTAINER:6379/0" \
  -e RECEIPTS_DIR=/app/storage/receipts \
  -e RBAC_OWNER_USER_ID=1 \
  -e ADMIN_AUTH_ENABLED=true \
  -e AUTH_DEBUG_ENABLED=false \
  -e MINI_SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  -e CRYPTO_PAYMENTS_ENABLED=false \
  -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
  -e CRYPTO_TRON_USDT_ENABLED=true \
  -e CRYPTO_TON_ENABLED=true \
  -e CRYPTO_DIRECT_WALLET_PAYMENTS_ENABLED=false \
  -e GAME_AUTO_DRAW_ENABLED=false \
  -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
  -e GAME_TAMBOLA_V2_ENABLED=false \
  -e DAVARNA_CRYPTO_ROTATION_PRODUCTION= \
  -e DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL= \
  --entrypoint uvicorn "$BACKEND_IMAGE" app.main:app --host 0.0.0.0 --port 8000 >/dev/null
TEST_CREATED=1

READY=0
for _ in $(seq 1 45); do
  if docker exec "$PREVIEW_TEST" python -c 'import urllib.request; assert urllib.request.urlopen("http://127.0.0.1:8000/health/db", timeout=3).read()==b"{\"ok\":true}"' >/dev/null 2>&1; then
    READY=1; break
  fi
  [[ "$(docker inspect -f '{{.State.Running}}' "$PREVIEW_TEST" 2>/dev/null || true)" == true ]] || break
  sleep 2
done
if [[ "$READY" != 1 ]]; then
  echo "===== PRIVATE PREVIEW FAILED (LAST LOG LINES; MAY CONTAIN SENSITIVE DATA) =====" >&2
  echo "For security, logs are not printed automatically. Inspect locally before sharing." >&2
  die "private backend health failed"
fi

echo "===== HTTP ROUTE / V1.3 MINI / AUTH TESTS ====="
docker exec -i "$PREVIEW_TEST" python - <<'PY'
import json, urllib.request, urllib.error
from app.core import config as c
from app.services.crypto_destination_state import production_rotation_enabled
from sqlalchemy.engine import make_url
db=make_url(c.DATABASE_URL)
assert db.host == "davarna-zero-mysql-20261110" and db.database == "davarna_zero_20261110"
assert c.RBAC_OWNER_USER_ID == 1
for flag in ("CRYPTO_PAYMENTS_ENABLED", "CRYPTO_AUTO_CONFIRM_ENABLED", "GAME_AUTO_DRAW_ENABLED", "GAME_AUTOPILOT_RUNTIME_ENABLED"):
    assert not getattr(c,flag), f"{flag} accidentally ON"
assert not production_rotation_enabled(), "Real wallet activation gate must remain OFF"
base="http://127.0.0.1:8000"
def fetch(path):
    return urllib.request.urlopen(base+path, timeout=5).read()
assert json.loads(fetch("/health/db"))["ok"] is True
html=fetch("/mini/index.html")
js=fetch("/mini/app.js")
assert b"superadmin-workspace-v13" in html
assert "افزودن یا تغییر آدرس دریافت".encode() in html
assert b"crypto-address-initialize-production" in js
assert b"crypto-address-activate-production" in js
print("PASS: Mini V1.3 / add / change / activation controls")
schema=json.loads(fetch("/openapi.json"))
paths=schema["paths"]
for p in (
    "/bot/admin/crypto-wallets",
    "/bot/admin/crypto-wallets/add",
    "/bot/admin/crypto-wallets/propose",
    "/bot/admin/crypto-wallets/activate",
    "/mini-api/admin/super/crypto-address-initialize-production",
    "/mini-api/admin/super/crypto-address-activate-production",
):
    assert p in paths, p
    print("PASS: registered route",p)
for p in ("/bot/admin/crypto-wallets", "/mini-api/admin/super/crypto-settings"):
    try:
        fetch(p)
    except urllib.error.HTTPError as e:
        assert e.code in (401,403), (p, e.code)
        print("PASS: anonymous wallet manager denied",p,e.code)
    else:
        raise RuntimeError("Anonymous wallet manager access enabled: "+p)
print("PASS: owner ID=1, all payments/workers OFF, network=private")
PY

echo "===== VERIFY NO NEW FINANCIAL RECORDS AND LIVE IMAGES UNCHANGED ====="
for table in wallets wallet_txs games game_purchases crypto_deposit_requests deposit_requests withdraw_requests; do
  [[ "$(sql "SELECT COUNT(*) FROM $table")" == 0 ]] || die "private DB unexpectedly changed: $table"
done
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$PROD_API" ]] || die "live backend image changed"
[[ "$(docker inspect -f '{{.Image}}' davarna-bot)" == "$PROD_BOT" ]] || die "live bot image changed"
[[ "$(docker inspect -f '{{.Image}}' davarna-mysql)" == "$PROD_MYSQL" ]] || die "live MySQL image changed"
echo "===== PRIVATE OWNER WALLET BOT + MINI STAGING PASS ====="
echo "BACKEND_IMAGE=$BACKEND_IMAGE"
echo "BOT_IMAGE=$BOT_IMAGE (NOT RUN)"
echo "LIVE_PRODUCTION_CHANGED=false"
echo "REAL_CRYPTO_ENABLED=false"
echo "CRYPTO_ADDRESS_WRITES=false"
echo "STAGING_API_STOPPED_ON_EXIT=true"
