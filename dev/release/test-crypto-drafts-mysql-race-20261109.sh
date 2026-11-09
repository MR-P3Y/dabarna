#!/usr/bin/env bash
# #30: migration contract in a NEW, limited-permission MySQL test database.
# No Production schema changes, no address rotation, no restart, no ledger writes.
set -Eeuo pipefail
umask 077
ROOT=/opt/davarna-v2
BRANCH=feature/roadmap-crypto-rules-ui-20261108
IMAGE=davarna-backend:finance-pr31-90f6670
TEST_DB=davarna_crypto_race_test_20261109
TEST_USER=davarna_rot_race_0013
WORK=""
CREATED_USER=0
die(){ echo "BLOCKER: $*" >&2; exit 2; }
[[ "$(id -u)" == 0 ]] || die "root required"
[[ "${DAVARNA_CRYPTO_RACE_TEST_APPROVAL:-}" == ISOLATED_SCHEMA_ONLY ]] || die "test-only approval flag missing"
SOURCE="${DAVARNA_CRYPTO_RACE_TEST_SOURCE_SHA:-}"
[[ "$SOURCE" =~ ^[0-9a-f]{40}$ ]] || die "pinned source SHA required"
exec 9>/run/davarna-crypto-migration-test.lock
flock -n 9 || die "another test running"
cd "$ROOT"
git cat-file -e "$SOURCE^{commit}" || die "source SHA not fetched"
[[ "$(git rev-parse "origin/$BRANCH")" == "$SOURCE" ]] || die "reviewed branch SHA changed"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$IMAGE" ]] || die "unexpected Production backend image"
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$(docker image inspect -f '{{.Id}}' "$IMAGE")" ]] || die "running Production backend differs"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || die "Production container unhealthy: $c"
done

mysql_query(){
  docker exec davarna-mysql sh -ec 'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql -uroot -N -B -e "$1"' sh "$1"
}
db_hex="$(printf '%s' "$TEST_DB" | od -An -tx1 | tr -d ' \n')"
user_hex="$(printf '%s' "$TEST_USER" | od -An -tx1 | tr -d ' \n')"
[[ "$(mysql_query "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=0x$db_hex")" == 0 ]] || die "test database exists; inspect before retry"
[[ "$(mysql_query "SELECT COUNT(*) FROM mysql.user WHERE user=0x$user_hex")" == 0 ]] || die "test account exists; inspect before retry"
PROD_REV="$(docker exec davarna-mysql sh -ec 'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql -uroot -N -B "$MYSQL_DATABASE" -e "SELECT version_num FROM alembic_version"')"
[[ "$PROD_REV" == 20261108_0012 ]] || die "Production revision changed"
echo "PASS: isolated test schema/account do not exist; Production at 20261108_0012"

cleanup(){
  rc=$?
  trap - EXIT
  if [[ "$CREATED_USER" == 1 ]]; then
    if mysql_query "DROP USER '$TEST_USER'@'%'" >/dev/null; then
      echo "PASS: restricted staging MySQL account removed"
    else
      echo "WARNING: failed to remove staging account; investigate safely" >&2
    fi
  fi
  if [[ -n "$WORK" && -d "$WORK" ]]; then rm -rf -- "$WORK"; fi
  exit "$rc"
}
trap cleanup EXIT

WORK="$(mktemp -d /tmp/davarna-crypto-migration.XXXXXX)"
git archive "$SOURCE" -- backend | tar -x -C "$WORK"
python3 - "$WORK" <<'PY'
import ast, pathlib, sys
base = pathlib.Path(sys.argv[1])
for rel in (
    "backend/alembic/versions/20261109_0013_crypto_destination_versions.py",
    "backend/app/models/crypto_destination_version.py",
    "backend/tests/mysql_crypto_destination_race.py",
):
    path = base / rel
    ast.parse(path.read_text(encoding="utf8"), filename=rel)
print("PASS: Python concurrent test syntax")
PY

PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
# All identifiers below are fixed strings, not external user input.
printf 'CREATE DATABASE %s CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n' "$TEST_DB" \
 | docker exec -i davarna-mysql sh -ec 'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql -uroot'
printf "CREATE USER '%s'@'%%' IDENTIFIED BY '%s';\n" "$TEST_USER" "$PASSWORD" \
 | docker exec -i davarna-mysql sh -ec 'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql -uroot'
CREATED_USER=1
printf "GRANT ALL PRIVILEGES ON %s.* TO '%s'@'%%';\n" "$TEST_DB" "$TEST_USER" \
 | docker exec -i davarna-mysql sh -ec 'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql -uroot'
printf 'DATABASE_URL=mysql+pymysql://%s:%s@davarna-mysql:3306/%s\n' \
 "$TEST_USER" "$PASSWORD" "$TEST_DB" > "$WORK/test-db.env"
chmod 600 "$WORK/test-db.env"
unset PASSWORD

echo "===== TEST CONCURRENT DRAFTS WITH ISOLATED MYSQL ====="
docker run --rm --network davarna_default --read-only \
 --memory 512m --cpus 1 --pids-limit 128 \
 --cap-drop ALL --security-opt no-new-privileges \
 --tmpfs /tmp:rw,nosuid,nodev \
 --env-file "$WORK/test-db.env" \
 -e REDIS_URL=redis://127.0.0.1:6379/0 \
 -e RECEIPTS_DIR=/tmp/receipts \
 -e DAVARNA_ROTATION_RACE_SCOPE=ISOLATED_RACE_ONLY \
 -e PYTHONPATH=/app -e PYTHONDONTWRITEBYTECODE=1 \
 -v "$WORK/backend:/app:ro" -w /app \
 --entrypoint python "$IMAGE" /app/tests/mysql_crypto_destination_race.py

AFTER="$(docker exec davarna-mysql sh -ec 'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql -uroot -N -B "$MYSQL_DATABASE" -e "SELECT version_num FROM alembic_version"')"
[[ "$AFTER" == "$PROD_REV" ]] || die "Production revision unexpectedly changed"
echo "PASS: Production schema unchanged ($AFTER)"
echo "PASS: test database $TEST_DB retained for inspection; no production rollout"
