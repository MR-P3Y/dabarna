#!/usr/bin/env bash
# Prepare a PERSISTENT, EMPTY, independent MySQL for Davarna zero-km launch.
# Does not attach the production bot/backend and never reads/writes the old DB.
# INTENTIONALLY DOES NOT START A SECOND TELEGRAM BOT OR CHANGE ROUTING.
set -Eeuo pipefail
umask 077

ROOT=/opt/davarna-v2
REF="${DAVARNA_ZERO_KM_PREPARE_REF:?Pin 40-character source SHA}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo "BLOCKED: invalid source SHA" >&2; exit 2; }
[[ "${DAVARNA_ZERO_KM_PREPARE_APPROVAL:-}" == "PREPARE_SEPARATE_EMPTY_MYSQL_ONLY" ]] || {
  echo "BLOCKED: explicit prepare-only approval missing" >&2; exit 2;
}
[[ "$(id -u)" == 0 ]] || { echo "BLOCKED: root required" >&2; exit 2; }
cd "$ROOT"
git cat-file -e "$REF^{commit}"

DB=davarna_zero_20261110
CONTAINER=davarna-zero-mysql-20261110
VOLUME=davarna_zero_mysql_data_20261110
NETWORK=davarna-zero-db-net-20261110
SECRETS_DIR=/root/davarna-zero-km-20261110
SECRETS_FILE="$SECRETS_DIR/mysql-secrets.env"
MYSQL_IMAGE=mysql:8.4
BASE=davarna-backend:superadmin-v11-rbac-7101e5c
BASE_ID=sha256:42a77764a254d33f058fb1b606b4a274704975feadce717aa47bb336a3cb9d45

echo "===== STRICT TARGET GUARDS ====="
[[ "$CONTAINER" != davarna-mysql && "$VOLUME" != davarna_mysql_data ]] || exit 2
[[ ! -e "$SECRETS_DIR" ]] || { echo "BLOCKED: prepared secrets already exist; no overwrite"; exit 2; }
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "BLOCKED: target container already exists; no reuse"; exit 2
fi
if docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  echo "BLOCKED: target volume already exists; no reuse"; exit 2
fi
if docker network inspect "$NETWORK" >/dev/null 2>&1; then
  echo "BLOCKED: target network already exists; no reuse"; exit 2
fi
docker image inspect "$MYSQL_IMAGE" >/dev/null || { echo "BLOCKED: mysql:8.4 not cached"; exit 2; }
[[ "$(docker image inspect -f '{{.Id}}' "$BASE")" == "$BASE_ID" ]] || {
  echo "BLOCKED: test Python image changed"; exit 2;
}
for service in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$service")" == healthy ]] || {
    echo "BLOCKED: unhealthy production service: $service"; exit 2;
  }
done
echo "PASS: existing Production containers preserved"
echo "===== CREATE DEDICATED PERSISTENT RESOURCES ====="
install -d -m 0700 "$SECRETS_DIR"
ROOTPASS="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
APPPASS="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
printf 'MYSQL_DATABASE=%s\nMYSQL_USER=%s\nMYSQL_ROOT_PASSWORD=%s\nMYSQL_PASSWORD=%s\n' \
  "$DB" "davarna_zero_app" "$ROOTPASS" "$APPPASS" > "$SECRETS_FILE"
chmod 0600 "$SECRETS_FILE"

docker volume create "$VOLUME" >/dev/null
docker network create --internal "$NETWORK" >/dev/null
# A unique internal network; no published host port or mount of old volumes.
docker run -d --name "$CONTAINER" --network "$NETWORK" \
  --restart unless-stopped \
  --memory=1280m --memory-swap=1280m \
  --security-opt no-new-privileges \
  --mount "type=volume,src=$VOLUME,dst=/var/lib/mysql" \
  --env-file "$SECRETS_FILE" \
  "$MYSQL_IMAGE" \
  --innodb-buffer-pool-size=256M \
  --mysql-native-password=ON \
  --log-bin-trust-function-creators=ON \
  --character-set-server=utf8mb4 \
  --collation-server=utf8mb4_unicode_ci \
  >/dev/null

echo "===== WAIT FOR INDEPENDENT MYSQL ====="
READY=0
for _ in $(seq 1 90); do
  if docker exec -e MYSQL_PWD="$APPPASS" "$CONTAINER" mysql \
     -udavarna_zero_app "$DB" --batch --skip-column-names \
     -e 'SELECT 1' >/dev/null 2>&1; then
    READY=1; break
  fi
  sleep 2
done
[[ "$READY" == 1 ]] || { echo "BLOCKED: new MySQL failed to become ready; persistent resources retained for diagnosis"; exit 3; }

TRUST="$(docker exec -e MYSQL_PWD="$ROOTPASS" "$CONTAINER" mysql \
  -uroot --batch --skip-column-names -e 'SELECT @@GLOBAL.log_bin_trust_function_creators')"
[[ "$TRUST" == 1 ]] || { echo "BLOCKED: required trigger trust disabled"; exit 3; }

echo "===== MIGRATE + SEED NEW EMPTY DATABASE ONLY ====="
WORK="$(mktemp -d /tmp/davarna-zero-km-src.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
git archive "$REF" -- backend | tar -x -C "$WORK"
DB_URL="mysql+pymysql://davarna_zero_app:$APPPASS@$CONTAINER/$DB?charset=utf8mb4"

docker run --rm --network "$NETWORK" \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --memory=512m --memory-swap=512m \
  --tmpfs /tmp:rw,nosuid,size=128m \
  -v "$WORK/backend:/app:ro" -w /app \
  -e DATABASE_URL="$DB_URL" \
  -e RECEIPTS_DIR=/tmp/receipts \
  -e CRYPTO_PAYMENTS_ENABLED=false \
  -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
  -e DAVARNA_CRYPTO_ROTATION_PRODUCTION= \
  -e DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL= \
  -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
  -e GAME_AUTO_DRAW_ENABLED=false \
  -e REDIS_URL=redis://127.0.0.1:6379/15 \
  --entrypoint sh "$BASE" -c 'alembic upgrade head && python -m app.scripts.seed_initial'

echo "===== ENFORCE ZERO-KM FINANCIAL COUNTS ====="
for table in users wallets wallet_txs games game_purchases crypto_deposit_requests deposit_requests withdraw_requests; do
  COUNT="$(docker exec -e MYSQL_PWD="$APPPASS" "$CONTAINER" mysql \
    -udavarna_zero_app "$DB" --batch --skip-column-names \
    -e "SELECT COUNT(*) FROM $table;" | tr -d '\r\n')"
  [[ "$COUNT" == 0 ]] || { echo "BLOCKED: nonempty new DB table $table ($COUNT)"; exit 4; }
  echo "PASS: $table=0"
done
REV="$(docker exec -e MYSQL_PWD="$APPPASS" "$CONTAINER" mysql \
  -udavarna_zero_app "$DB" --batch --skip-column-names \
  -e 'SELECT version_num FROM alembic_version;' | tr -d '\r\n')"
[[ "$REV" == 20261108_0012 ]] || { echo "BLOCKED: unexpected schema head $REV"; exit 4; }
CFG_COUNT="$(docker exec -e MYSQL_PWD="$APPPASS" "$CONTAINER" mysql \
  -udavarna_zero_app "$DB" --batch --skip-column-names \
  -e 'SELECT COUNT(*) FROM game_autopilot_configs WHERE enabled <> 0;' | tr -d '\r\n')"
[[ "$CFG_COUNT" == 0 ]] || { echo "BLOCKED: autopilot enabled in fresh DB"; exit 4; }
echo "===== PERSISTENT NEW DATABASE READY (NOT CUT OVER) ====="
echo "DATABASE=$DB"
echo "CONTAINER=$CONTAINER"
echo "NETWORK=$NETWORK"
echo "VOLUME=$VOLUME"
echo "SECRETS_FILE=$SECRETS_FILE (private, never upload or paste)"
echo "SCHEMA_HEAD=$REV"
echo "PAYMENT_RUNTIME=OFF (not enabled by seed)"
echo "PRODUCTION_BACKEND_BOT_UNCHANGED=true"
echo "NEXT=build compatible clean-launch backend + owner bootstrap + gated cutover"
