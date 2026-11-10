#!/usr/bin/env bash
# Davarna clean-launch gate: verify full Alembic migration and initial seed on a
# BRAND-NEW disposable MySQL schema, with no access to live DB or Docker Compose.
# No production clone, data deletion, migration of balances or bot startup.
set -Eeuo pipefail
umask 077
ROOT=/opt/davarna-v2
REF="${DAVARNA_CLEAN_LAUNCH_TEST_REF:?Pin a verified 40-character Git SHA}"
APPROVAL="${DAVARNA_CLEAN_LAUNCH_TEST_APPROVAL:-}"
MYSQL_IMAGE=mysql:8.4
BASE=davarna-backend:superadmin-v11-rbac-7101e5c
BASE_ID=sha256:42a77764a254d33f058fb1b606b4a274704975feadce717aa47bb336a3cb9d45

[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo 'BLOCKED: SHA invalid' >&2; exit 2; }
[[ "$APPROVAL" == "RUN_FRESH_DISPOSABLE_DB_ONLY" ]] || {
  echo 'BLOCKED: disposable-only approval missing' >&2; exit 2;
}
cd "$ROOT"
git cat-file -e "$REF^{commit}"
[[ "$(docker image inspect -f '{{.Id}}' "$BASE")" == "$BASE_ID" ]] || {
  echo 'BLOCKED: pinned Python image changed' >&2; exit 2;
}
docker image inspect "$MYSQL_IMAGE" >/dev/null || {
  echo 'BLOCKED: mysql:8.4 image not cached' >&2; exit 2;
}
WORK="$(mktemp -d /tmp/davarna-clean-launch.XXXXXX)"
ID="${WORK##*.}"
DB_CONTAINER="davarna-clean-db-$ID"
NETWORK="davarna-clean-net-$ID"
CREATED_NET=0
CREATED_DB=0
cleanup() {
  rc=$?
  trap - EXIT INT TERM
  if (( CREATED_DB )); then docker rm -f "$DB_CONTAINER" >/dev/null 2>&1 || true; fi
  if (( CREATED_NET )); then docker network rm "$NETWORK" >/dev/null 2>&1 || true; fi
  rm -rf -- "$WORK"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "===== PINNED SOURCE ====="
git archive "$REF" -- backend | tar -x -C "$WORK"
echo "===== ISOLATED MYSQL: NO PRODUCTION HOST, VOLUME OR PORT ====="
docker network create --internal "$NETWORK" >/dev/null
CREATED_NET=1
ROOTPASS="$(python3 -c 'import secrets;print(secrets.token_urlsafe(36))')"
docker run -d --rm --name "$DB_CONTAINER" --network "$NETWORK" \
  --tmpfs /var/lib/mysql:rw,size=768m,mode=0700 \
  --tmpfs /tmp:rw,size=128m,mode=1777 \
  --memory=768m --memory-swap=768m --security-opt no-new-privileges \
  -e MYSQL_ROOT_PASSWORD="$ROOTPASS" \
  -e MYSQL_DATABASE=davarna_clean_launch_validation \
  "$MYSQL_IMAGE" --innodb-buffer-pool-size=64M --mysql-native-password=ON \
  --log-bin-trust-function-creators=ON >/dev/null
CREATED_DB=1
READY=0
for _ in $(seq 1 90); do
  if docker exec -e MYSQL_PWD="$ROOTPASS" "$DB_CONTAINER" \
    mysql -uroot --batch --skip-column-names \
      davarna_clean_launch_validation -e 'SELECT 1' >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 2
done
[[ "$READY" == 1 ]] || { echo 'BLOCKED: dedicated MySQL not ready' >&2; exit 3; }
TESTPASS="$(python3 -c 'import secrets;print(secrets.token_urlsafe(36))')"
docker exec -i -e MYSQL_PWD="$ROOTPASS" "$DB_CONTAINER" mysql -uroot \
  --batch --skip-column-names <<SQL
CREATE USER 'clean_launch_test'@'%' IDENTIFIED WITH mysql_native_password BY '$TESTPASS';
GRANT ALL PRIVILEGES ON davarna_clean_launch_validation.* TO 'clean_launch_test'@'%';
SQL
DB_URL="mysql+pymysql://clean_launch_test:$TESTPASS@$DB_CONTAINER/davarna_clean_launch_validation"

echo "===== DISPOSABLE-ONLY MYSQL TRIGGER PREFLIGHT ====="
# The pinned 20260916_0007 migration checks this variable and TRIGGER grants.
# Set at container startup ONLY on the ephemeral isolated MySQL; the live
# davarna-mysql instance, its global settings and named volume are untouched.
TRUST="$(docker exec -e MYSQL_PWD="$ROOTPASS" "$DB_CONTAINER" \
  mysql -uroot --batch --skip-column-names -e 'SELECT @@GLOBAL.log_bin_trust_function_creators')"
[[ "$TRUST" == 1 ]] || { echo "BLOCKED: isolated MySQL trigger setting unexpected" >&2; exit 3; }
echo "PASS: isolated MySQL trigger creation allowed"

echo "===== CLEAN MIGRATIONS + FRESH INITIAL SEED ====="
docker run --rm --network "$NETWORK" --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --memory=512m --memory-swap=512m --tmpfs /tmp:rw,nosuid,size=128m \
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
  --entrypoint sh "$BASE" -c \
  'alembic upgrade head && python -m app.scripts.seed_initial'

echo "===== VERIFY FRESH STATE AND NO IMPORTED FINANCIAL HISTORY ====="
# A fresh seeded database should contain only configuration, role and migration
# metadata; no wallet, game, purchase, deposit, or user financial records.
docker exec -i -e MYSQL_PWD="$ROOTPASS" "$DB_CONTAINER" \
  mysql -uroot davarna_clean_launch_validation --batch --skip-column-names <<'SQL'
SELECT 'schema_head', version_num FROM alembic_version;
SELECT 'configured_roles', COUNT(*) FROM roles;
SELECT 'configured_settings', COUNT(*) FROM app_settings;
SELECT 'fresh_users', COUNT(*) FROM users;
SELECT 'fresh_wallets', COUNT(*) FROM wallets;
SELECT 'fresh_wallet_ledger', COUNT(*) FROM wallet_txs;
SELECT 'fresh_games', COUNT(*) FROM games;
SELECT 'fresh_purchases', COUNT(*) FROM game_purchases;
SELECT 'fresh_crypto_invoices', COUNT(*) FROM crypto_deposit_requests;
SELECT 'fresh_bank_deposits', COUNT(*) FROM deposit_requests;
SELECT 'fresh_withdrawals', COUNT(*) FROM withdraw_requests;
SQL
# The assertions run within MySQL itself, failing loudly if any financial
# history was somehow injected into this isolated database.
for table in users wallets wallet_txs games game_purchases crypto_deposit_requests deposit_requests withdraw_requests; do
  count="$(docker exec -e MYSQL_PWD="$ROOTPASS" "$DB_CONTAINER" \
    mysql -uroot davarna_clean_launch_validation --batch --skip-column-names \
    -e "SELECT COUNT(*) FROM $table;" 2>/dev/null | tr -d '\r\n')"
  [[ "$count" == 0 ]] || { echo "BLOCKED: $table has $count rows" >&2; exit 4; }
done
echo "===== CLEAN-LAUNCH FRESH DB TEST PASS ====="
echo "SOURCE=$REF"
echo 'Only a disposable tmpfs MySQL was used. Production has NOT been touched.'
