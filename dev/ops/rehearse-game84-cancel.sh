#!/usr/bin/env bash
# Run ALL isolated MySQL finance smoke tests, including the exact Game 84 refund
# shape (one buyer / two purchases / six cards / 36,000). All rows roll back.
set -Eeuo pipefail
umask 077
cd /opt/davarna-v2
TEST_DB=davarna_tambola_v2_test_20261104
IMAGE=davarna-backend:rbac-pr14-e087c40bd471
BRANCH=ops/game84-refund-guard-20261107
[[ "$(id -u)" == 0 ]] || { echo "BLOCKER: root required"; exit 2; }
docker image inspect "$IMAGE" >/dev/null
git rev-parse --verify "origin/$BRANCH" >/dev/null
WORK="$(mktemp -d /tmp/davarna-game84-test.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
git archive "origin/$BRANCH" -- backend | tar -x -C "$WORK"
python3 - "$WORK/finance-env" <<'PY'
import json, os, subprocess, sys
data=json.loads(subprocess.check_output(["docker","inspect","davarna-backend"],text=True))[0]
env=dict(x.split("=",1) for x in data["Config"]["Env"] if "=" in x)
url=env.get("DATABASE_URL")
if not url: raise SystemExit("BLOCKER: DATABASE_URL not available")
with open(sys.argv[1],"w",encoding="utf-8") as f:
    f.write("DATABASE_URL=" + json.dumps(url) + "\n")
os.chmod(sys.argv[1], 0o600)
PY
echo "===== ISOLATED MYSQL FINANCIAL REHEARSAL (ROLLBACK) ====="
docker run --rm --network davarna_default --read-only --memory 512m --cpus 1 \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
  -v "$WORK/backend:/app:ro" \
  -v "$WORK/finance-env:/run/secrets/davarna_env:ro" \
  -e DAVARNA_FINANCE_TEST_DB="$TEST_DB" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e RECEIPTS_DIR=/tmp/receipts \
  -w /app "$IMAGE" \
  python -m unittest discover -s tests -p mysql_finance_smoke.py -v
echo "===== ALL ISOLATED MYSQL FINANCE TESTS PASSED ====="
