#!/usr/bin/env bash
# Test patched Mini App in DISPOSABLE containers; no live container recreated.
# MySQL integration suite is forcibly redirected to the isolated test schema.
set -Eeuo pipefail
umask 077
cd /opt/davarna-v2
BRANCH=fix/mini-superadmin-controls-20261107
TEST_DB=davarna_tambola_v2_test_20261104
IMAGE=davarna-backend:rbac-pr14-e087c40bd471

[[ "$(id -u)" == 0 ]] || { echo "BLOCKER: root required"; exit 2; }
git rev-parse --verify "origin/$BRANCH" >/dev/null
docker image inspect "$IMAGE" >/dev/null
[[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-backend)" == healthy ]] || {
  echo "BLOCKER: production backend unhealthy"; exit 2;
}
available=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
(( available > 512 * 1024 )) || { echo "BLOCKER: RAM under 512 MiB"; exit 2; }

WORK=$(mktemp -d /tmp/davarna-mini-super-XXXXXX)
chmod 0700 "$WORK"
trap 'rm -rf -- "$WORK"' EXIT
git archive "origin/$BRANCH" -- backend | tar -x -C "$WORK"

echo "===== STATIC JAVASCRIPT PARSER ====="
command -v node >/dev/null || { echo "BLOCKER: Node.js required for JavaScript syntax check"; exit 2; }
node --check "$WORK/backend/app/static/mini/app.js"

echo "===== SOURCE/VALIDATION TESTS (NO NETWORK) ====="
docker run --rm --network none --read-only --memory 384m --cpus 1 \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
  -v "$WORK/backend:/app:ro" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e RECEIPTS_DIR=/tmp/receipts \
  -e DATABASE_URL='sqlite+pysqlite:///:memory:' \
  -e REDIS_URL='redis://127.0.0.1:6379/0' \
  --entrypoint python -w /app "$IMAGE" \
  -m unittest discover -s tests -p test_mini_superadmin_*.py -v

echo "===== PRIVATE MYSQL CREDENTIALS (NEVER PRINTED) ====="
python3 - "$WORK/test-database.env" <<'PY'
import json, os, subprocess, sys
obj=json.loads(subprocess.check_output(["docker","inspect","davarna-backend"],text=True))[0]
env=dict(x.split("=",1) for x in obj["Config"]["Env"] if "=" in x)
url=env.get("DATABASE_URL")
if not url: raise SystemExit("BLOCKER: backend DATABASE_URL unavailable")
with open(sys.argv[1],"w",encoding="utf-8") as out:
    out.write("DATABASE_URL=" + json.dumps(url) + "\n")
os.chmod(sys.argv[1],0o600)
PY

echo "===== ISOLATED MYSQL BANK ADMIN E2E (ROLLBACK) ====="
docker run --rm --network davarna_default --read-only --memory 512m --cpus 1 \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
  -e DAVARNA_SUPER_BANK_TEST_DB="$TEST_DB" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e RECEIPTS_DIR=/tmp/receipts \
  -v "$WORK/backend:/app:ro" \
  -v "$WORK/test-database.env:/run/secrets/davarna_env:ro" \
  -w /app "$IMAGE" \
  python -m unittest discover -s tests -p mysql_super_bank_admin_e2e.py -v

echo "===== ALL MINI SUPERADMIN CONTROLS TESTS PASSED ====="
