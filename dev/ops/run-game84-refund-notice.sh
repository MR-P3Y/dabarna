#!/usr/bin/env bash
# Operator-approved: notify buyer of already-committed Game 84 refund exactly once.
# Does NOT re-run cancellation, modify wallets, deploy or restart services.
set -Eeuo pipefail
umask 077
cd /opt/davarna-v2
[[ "$(id -u)" == 0 ]] || { echo "BLOCKER: root required"; exit 2; }
REF=4bf5b15b88d29643452db153a55487f732f1102d
SOURCE=dev/ops/notify-game84-refund-once.py
[[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-backend)" == healthy ]] || { echo "BLOCKER: backend unhealthy"; exit 2; }
[[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-bot)" == healthy ]] || { echo "BLOCKER: bot unhealthy"; exit 2; }
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == davarna-backend:rbac-pr14-e087c40bd471 ]] || { echo "BLOCKER: backend image changed"; exit 2; }
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == davarna-bot:pr13-d9434cb10d71 ]] || { echo "BLOCKER: bot image changed"; exit 2; }
git cat-file -e "$REF^{commit}" || { echo "BLOCKER: tool commit unavailable; fetch branch first"; exit 2; }

# Use both actual production containers, no token values or hashes are output.
python3 - <<'PY'
import json
import subprocess
def env(container):
    obj=json.loads(subprocess.check_output(["docker","inspect",container],text=True))[0]
    return dict(x.split("=",1) for x in obj["Config"]["Env"] if "=" in x)
backend=env("davarna-backend").get("TELEGRAM_BOT_TOKEN")
bot=env("davarna-bot").get("TELEGRAM_BOT_TOKEN")
if not backend or not bot or backend != bot:
    raise SystemExit("BLOCKER: bot tokens absent or mismatch")
print("PASS: both containers use the same Telegram bot identity")
PY

FILE="$(mktemp /tmp/game84-notice.XXXXXX.py)"
chmod 0600 "$FILE"
trap 'rm -f -- "$FILE"' EXIT
git show "$REF:$SOURCE" > "$FILE"
python3 -m py_compile "$FILE"

echo "===== READ-ONLY REFUND NOTICE CHECK ====="
docker exec -i davarna-backend python - --check-only < "$FILE"
echo "===== GAME 84 PRIVATE REFUND NOTICE (ONE ATTEMPT) ====="
docker exec -i davarna-backend python - < "$FILE"
echo "===== GAME 84 NOTICE COMPLETE ====="
