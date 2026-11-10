#!/usr/bin/env bash
# Disposable MySQL concurrency gate for wallet address rotation.
# Never connect to Production; no Compose, no named volumes, no existing containers.
set -Eeuo pipefail
umask 077

ROOT=/opt/davarna-v2
REF="${DAVARNA_WALLET_MYSQL_TEST_REF:?Pin a verified Git commit SHA}"
BASE=davarna-backend:superadmin-v11-rbac-7101e5c
BASE_ID=sha256:42a77764a254d33f058fb1b606b4a274704975feadce717aa47bb336a3cb9d45
MYSQL_IMAGE=mysql:8.4
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || { echo 'BLOCKER: invalid pinned SHA' >&2; exit 2; }
[[ "${DAVARNA_WALLET_MYSQL_TEST_APPROVAL:-}" == "RUN_DISPOSABLE_MYSQL_ONLY" ]] || {
  echo 'BLOCKER: opt-in for disposable test missing' >&2; exit 2;
}
cd "$ROOT"
git cat-file -e "$REF^{commit}"
[[ "$(docker image inspect -f '{{.Id}}' "$BASE")" == "$BASE_ID" ]] || {
  echo 'BLOCKER: tested backend image changed' >&2; exit 2;
}
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == sha256:* ]] || {
  echo 'BLOCKER: live backend not found (read-only check)' >&2; exit 2;
}
# Reuse an already-downloaded MySQL image; do not pull unexpectedly during test.
docker image inspect "$MYSQL_IMAGE" >/dev/null || {
  echo 'BLOCKER: mysql:8.4 not cached; pull it explicitly before retrying' >&2; exit 2;
}
WORK=$(mktemp -d /tmp/davarna-mysql-rotation.XXXXXX)
ID=${WORK##*.}
NETWORK="wallet-rot-test-$ID"
DB_CONTAINER="davarna-wallet-mysql"
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

echo '===== ISOLATED PRECONDITIONS ====='
if docker inspect "$DB_CONTAINER" >/dev/null 2>&1; then
  echo 'BLOCKER: disposable container name already exists; refusing reuse' >&2; exit 2
fi
if docker network inspect "$NETWORK" >/dev/null 2>&1; then
  echo 'BLOCKER: test network name already exists; refusing reuse' >&2; exit 2
fi
git archive "$REF" -- backend | tar -x -C "$WORK"
# Ensure the test ref still contains exactly the approved isolated DB host/schema.
grep -Fq 'parsed.host == "davarna-wallet-mysql"' "$WORK/backend/tests/test_crypto_destination_mysql_concurrency.py"
grep -Fq 'parsed.database == "davarna_wallet_rotation_test"' "$WORK/backend/tests/test_crypto_destination_mysql_concurrency.py"
grep -Fq 'url.host == "davarna-wallet-mysql"' "$WORK/backend/app/services/crypto_destination_state.py"

echo '===== PRIVATE NETWORK / EPHEMERAL MYSQL ====='
docker network create --internal "$NETWORK" >/dev/null
CREATED_NET=1
PASS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')
# The database exists only inside this container's anonymous tmpfs. No host volume,
# no host port bindings, no network attachment to any existing container.
docker run -d --rm --name "$DB_CONTAINER" --network "$NETWORK" \
  --tmpfs /var/lib/mysql:rw,size=768m,mode=0700 \
  --tmpfs /tmp:rw,size=128m,mode=1777 \
  --memory=768m --memory-swap=768m \
  --security-opt no-new-privileges \
  -e MYSQL_ROOT_PASSWORD="$PASS" \
  -e MYSQL_DATABASE=davarna_wallet_rotation_test \
  "$MYSQL_IMAGE" --innodb-buffer-pool-size=64M --mysql-native-password=ON >/dev/null
CREATED_DB=1

echo '===== WAIT FOR DEDICATED DATABASE ====='
READY=0
for _ in $(seq 1 90); do
  if docker exec -e MYSQL_PWD="$PASS" "$DB_CONTAINER" mysql -uroot \
     --batch --skip-column-names -e 'SELECT DATABASE();' \
     davarna_wallet_rotation_test >/dev/null 2>&1; then
    READY=1; break
  fi
  sleep 2
done
[[ "$READY" == 1 ]] || { echo 'BLOCKER: disposable MySQL did not become ready' >&2; exit 2; }

echo '===== CREATE DISPOSABLE COMPATIBLE TEST USER ====='
# mysql:8.4 defaults to caching_sha2_password; the existing pinned Python
# image lacks cryptography for PyMySQL's RSA handshake. Enable mysql_native_password
# ONLY on the ephemeral container, and grant ONLY this disposable schema.
# Never modify any production MySQL account or authentication setting.
TEST_PASS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')
docker exec -i -e MYSQL_PWD="$PASS" "$DB_CONTAINER" mysql -uroot \
  --batch --skip-column-names <<SQL
CREATE USER 'wallet_rotation_test'@'%' IDENTIFIED WITH mysql_native_password BY '${TEST_PASS}';
GRANT ALL PRIVILEGES ON davarna_wallet_rotation_test.* TO 'wallet_rotation_test'@'%';
SQL
echo '===== CONCURRENT TRANSACTION TESTS ====='
# Supply URL via environment without printing credentials in test output.
URL="mysql+pymysql://wallet_rotation_test:${TEST_PASS}@davarna-wallet-mysql/davarna_wallet_rotation_test"
docker run --rm --network "$NETWORK" --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,size=128m \
  --memory=512m --memory-swap=512m \
  -e DATABASE_URL="$URL" \
  -e DAVARNA_WALLET_MYSQL_CONCURRENCY=I_ACK_DISPOSABLE_DB \
  -e DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL=I_ACK_DISPOSABLE_DB_ONLY \
  -e GAME_AUTOPILOT_RUNTIME_ENABLED=false \
  -e GAME_AUTO_DRAW_ENABLED=false \
  -e CRYPTO_AUTO_CONFIRM_ENABLED=false \
  -e REDIS_URL=redis://127.0.0.1:6379/15 \
  -e RECEIPTS_DIR=/tmp/receipts \
  -v "$WORK/backend:/app:ro" -w /app --entrypoint python "$BASE" \
  -m unittest discover -s tests -p 'test_crypto_destination_mysql_concurrency.py' -v

echo '===== LATE-TRANSFER SAFETY TESTS (NO CREDIT) ====='
docker run --rm --network "$NETWORK" --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,size=128m \
  -e DATABASE_URL="$URL" \
  -e DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL=I_ACK_DISPOSABLE_DB_ONLY \
  -e REDIS_URL=redis://127.0.0.1:6379/15 \
  -e RECEIPTS_DIR=/tmp/receipts \
  -v "$WORK/backend:/app:ro" -w /app --entrypoint python "$BASE" \
  -m unittest discover -s tests -p 'test_crypto_late_transfer_inbox_isolated.py' -v

echo '===== DISPOSABLE MYSQL CONCURRENCY PASS ====='
echo "SOURCE=$REF"
echo 'No production database, wallet or Docker Compose change made.'
