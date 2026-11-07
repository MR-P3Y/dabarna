#!/usr/bin/env bash
# Integrated regression: PR18 forum UX + PR19 Mini App superadmin controls.
# Executes pinned merged source in disposable read-only containers only.
# MySQL E2E forcibly uses isolated TEST database; rolls back all test changes.
set -Eeuo pipefail
umask 077
ROOT=/opt/davarna-v2
SRC=e7517922f08685be99a8f55564da1ad22abeddac
TEST_DB=davarna_tambola_v2_test_20261104
BOT_IMAGE=davarna-bot:pr13-d9434cb10d71
BACKEND_IMAGE=davarna-backend:rbac-pr14-e087c40bd471
cd "$ROOT"
[[ "$(id -u)" == 0 ]] || { echo "BLOCKER: root user required"; exit 2; }
git cat-file -e "$SRC^{commit}" || { echo "BLOCKER: reviewed source commit not fetched"; exit 2; }
git merge-base --is-ancestor "$SRC" origin/feature/ui-ux-refresh-tambola-v2-20261106 || {
  echo "BLOCKER: reviewed source does not belong to feature branch"; exit 2;
}
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$BACKEND_IMAGE" ]] || {
  echo "BLOCKER: production Backend image changed"; exit 2;
}
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == "$BOT_IMAGE" ]] || {
  echo "BLOCKER: production Bot image changed"; exit 2;
}
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || {
    echo "BLOCKER: production service unhealthy: $c"; exit 2;
  }
done
command -v node >/dev/null || { echo "BLOCKER: node executable unavailable"; exit 2; }
WORK="$(mktemp -d /tmp/davarna-merged-ui-tests.XXXXXX)"
chmod 0700 "$WORK"
trap 'rm -rf -- "$WORK"' EXIT
git archive "$SRC" -- backend davarna-bot | tar -x -C "$WORK"

echo "===== MERGED MINI JAVASCRIPT SYNTAX ====="
node --check "$WORK/backend/app/static/mini/app.js"

echo "===== MERGED TELEGRAM BOT TESTS (NO NETWORK) ====="
docker run --rm --network none --read-only --memory 512m --cpus 1 \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
  -v "$WORK/davarna-bot:/app:ro" \
  -e TELEGRAM_BOT_TOKEN='123456789:TEST_ONLY' \
  -e PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python -w /app "$BOT_IMAGE" \
  -m unittest discover -s tests -p 'test_*.py' -v

echo "===== MERGED MINI BACKEND UNIT TESTS (NO NETWORK) ====="
docker run --rm --network none --read-only --memory 512m --cpus 1 \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
  -v "$WORK/backend:/app:ro" \
  -e DATABASE_URL='sqlite+pysqlite:///:memory:' \
  -e REDIS_URL='redis://127.0.0.1:6379/0' \
  -e RECEIPTS_DIR=/tmp/receipts -e PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python -w /app "$BACKEND_IMAGE" \
  -m unittest discover -s tests -p test_mini_superadmin_*.py -v

echo "===== MERGED FORUM BACKEND UNIT TESTS (NO NETWORK) ====="
docker run --rm --network none --read-only --memory 384m --cpus 1 \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
  -v "$WORK/backend:/app:ro" \
  -e DATABASE_URL='sqlite+pysqlite:///:memory:' \
  -e REDIS_URL='redis://127.0.0.1:6379/0' \
  -e RECEIPTS_DIR=/tmp/receipts -e PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint python -w /app "$BACKEND_IMAGE" \
  -m unittest discover -s tests -p test_user_forum_created_notice.py -v

echo "===== PRIVATE MYSQL CONNECTION CONFIG (NOT PRINTED) ====="
python3 - "$WORK/isolated-db.env" <<'PY'
import json, os, subprocess, sys
container=json.loads(subprocess.check_output(["docker","inspect","davarna-backend"], text=True))[0]
env=dict(pair.split("=",1) for pair in container["Config"]["Env"] if "=" in pair)
url=env.get("DATABASE_URL")
if not url:
    raise SystemExit("BLOCKER: production backend DATABASE_URL missing")
with open(sys.argv[1],"w",encoding="utf-8") as f:
    f.write("DATABASE_URL=" + json.dumps(url) + "\n")
os.chmod(sys.argv[1],0o600)
PY

echo "===== MERGED SUPERADMIN MYSQL TEST: ISOLATED TEST DB ONLY ====="
docker run --rm --network davarna_default --read-only --memory 512m --cpus 1 \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
  -v "$WORK/backend:/app:ro" \
  -v "$WORK/isolated-db.env:/run/secrets/davarna_env:ro" \
  -e DAVARNA_SUPER_BANK_TEST_DB="$TEST_DB" \
  -e RECEIPTS_DIR=/tmp/receipts -e PYTHONDONTWRITEBYTECODE=1 \
  -w /app "$BACKEND_IMAGE" \
  python -m unittest discover -s tests -p mysql_super_bank_admin_e2e.py -v

echo "===== MERGED PR18 + PR19 TESTS PASSED; PRODUCTION UNCHANGED ====="
