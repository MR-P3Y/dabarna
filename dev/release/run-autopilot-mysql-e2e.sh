#!/usr/bin/env bash
# Run isolated MySQL Autopilot regression test. No production DB writes.
set -Eeuo pipefail
umask 077
cd /opt/davarna-v2

BRANCH=test/autopilot-mysql-e2e-20261106
TEST_DB=davarna_tambola_v2_test_20261104
IMAGE=davarna-backend:pr13-d9434cb10d71

[[ "$(id -u)" == 0 ]] || { echo "BLOCKER: run as root"; exit 2; }
[[ "$(git rev-parse --is-inside-work-tree)" == true ]] || exit 2
git rev-parse --verify "origin/$BRANCH" >/dev/null
docker image inspect "$IMAGE" >/dev/null

if (( $(awk '/^MemAvailable:/ {print $2}' /proc/meminfo) < 512*1024 )); then
  echo "BLOCKER: less than 512 MiB available memory"
  exit 2
fi

WORK=$(mktemp -d /tmp/davarna-autopilot-mysql.XXXXXX)
trap 'rm -rf -- "$WORK"' EXIT
chmod 0700 "$WORK"
git archive "origin/$BRANCH" | tar -x -C "$WORK"
test -f "$WORK/backend/tests/mysql_autopilot_e2e.py"

echo "===== PREPARE PRIVATE CONNECTION (NO SECRET OUTPUT) ====="
python3 - "$WORK/test-db.env" <<'PY'
import json
import os
import subprocess
import sys

obj = json.loads(subprocess.check_output(
    ["docker", "inspect", "davarna-backend"], text=True
))[0]
env = dict(item.split("=", 1) for item in obj["Config"]["Env"] if "=" in item)
url = env.get("DATABASE_URL")
if not url:
    raise SystemExit("BLOCKER: backend DATABASE_URL unavailable")
with open(sys.argv[1], "w", encoding="utf-8") as f:
    f.write("DATABASE_URL=" + json.dumps(url) + "\n")
os.chmod(sys.argv[1], 0o600)
PY

echo "===== AUTOPILOT ISOLATED MYSQL E2E ====="
docker run --rm \
  --network davarna_default \
  --read-only \
  --memory 512m \
  --cpus 1 \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev \
  -e DAVARNA_AUTOPILOT_E2E_DB="$TEST_DB" \
  -e RECEIPTS_DIR=/tmp/receipts \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$WORK/backend:/app:ro" \
  -v "$WORK/test-db.env:/run/secrets/davarna_env:ro" \
  -w /app \
  "$IMAGE" \
  python -m unittest discover -s tests -p mysql_autopilot_e2e.py -v

echo "===== AUTOPILOT MYSQL E2E PASSED ====="
