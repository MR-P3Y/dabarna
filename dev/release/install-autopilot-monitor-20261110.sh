#!/usr/bin/env bash
# Pin, offline-test and install 5-minute read-only monitoring (not a backend deploy).
set -Eeuo pipefail
umask 077
die(){ echo "BLOCKER: $*" >&2; exit 2; }
ROOT=/opt/davarna-v2
REF="${DAVARNA_MONITOR_INSTALL_REF:?pinned commit required}"
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || die "invalid SHA"
[[ "${DAVARNA_MONITOR_INSTALL_APPROVAL:-}" == "INSTALL_5MIN_HEALTH_MONITOR_ALERTS" ]] || die "explicit monitoring installation approval missing"
[[ "$(id -u)" == 0 ]] || die "root required"
cd "$ROOT"
git cat-file -e "$REF^{commit}" || die "commit unavailable"
exec 9>/run/davarna-auto-draw-recovery.lock
flock -n 9 || die "another release holds lock"
command -v docker >/dev/null || die "Docker missing"
command -v python3 >/dev/null || die "Python3 missing"
command -v cron >/dev/null || die "cron daemon binary missing"
systemctl is-active --quiet cron || die "cron.service is inactive; stop and investigate before installation"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
 [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || die "container not healthy: $c"
done
echo "===== CHECK EXISTING BOT ADMIN ALERTS ROUTE (NO TOKENS PRINTED) ====="
docker exec davarna-bot python - <<'PY'
from bot.config import settings
from bot.services.admin_topics import topic_id,forum_enabled
assert settings.TELEGRAM_BOT_TOKEN and forum_enabled(),"bot token or admin forum missing"
assert topic_id("alerts") is not None,"admin alerts and general topics both missing"
print("PASS: management alert topic is configured")
PY
echo "===== STAGE PINNED MONITOR FILES ====="
WORK="$(mktemp -d /tmp/davarna-monitor-stage.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
git show "$REF:dev/release/audit-autopilot-health-readonly-20261110.sh" > "$WORK/health.sh"
git show "$REF:dev/release/autopilot-monitor-20261110.py" > "$WORK/autopilot-monitor-20261110.py"
git show "$REF:dev/release/test-autopilot-monitor-20261110.py" > "$WORK/test-autopilot-monitor-20261110.py"
bash -n "$WORK/health.sh"
python3 - "$WORK/autopilot-monitor-20261110.py" "$WORK/test-autopilot-monitor-20261110.py" <<'PY'
import ast,sys
for path in sys.argv[1:]:ast.parse(open(path,encoding="utf-8").read())
print("PASS: Python syntax")
PY
echo "===== OFFLINE MONITOR UNIT TESTS ====="
python3 "$WORK/test-autopilot-monitor-20261110.py"
echo "===== INSTALL HOST MONITOR (NO DOCKER RESTART) ====="
install -d -m 0700 /var/lib/davarna-autopilot-monitor
install -d -m 0750 /usr/local/sbin
RUNNER=/usr/local/sbin/davarna-autopilot-health-audit.sh
MONITOR=/usr/local/sbin/davarna-autopilot-monitor.py
CRON=/etc/cron.d/davarna-autopilot-monitor
if [[ -e "$RUNNER" || -e "$MONITOR" || -e "$CRON" ]]; then
 die "existing monitor installation detected; do not overwrite without inspection"
fi
install -m 0700 "$WORK/health.sh" "$RUNNER"
install -m 0700 "$WORK/autopilot-monitor-20261110.py" "$MONITOR"
echo "===== READ-ONLY LIVE SMOKE TEST (NO SENDING) ====="
python3 "$MONITOR" --dry-run
echo "===== TEST REAL ADMIN TELEGRAM ALERT ROUTE (ONE TEST MESSAGE) ====="
python3 "$MONITOR" --test-notification || die "Telegram delivery failed; cron NOT installed"
echo "===== REGISTER CRON EVERY FIVE MINUTES ====="
tmp="$(mktemp /tmp/davarna-monitor-cron.XXXXXX)"
printf 'SHELL=/bin/sh\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n*/5 * * * * root /usr/bin/python3 /usr/local/sbin/davarna-autopilot-monitor.py >> /var/log/davarna-autopilot-monitor.log 2>&1\n' >"$tmp"
install -m 0644 "$tmp" "$CRON"
rm -f "$tmp"
echo "===== INITIAL RECORDED CHECK ====="
python3 "$MONITOR"
echo "===== AUTOPILOT MONITOR INSTALLED ====="
echo "SCHEDULE=every 5 minutes"
echo "HISTORY=/var/lib/davarna-autopilot-monitor/history.jsonl"
echo "STATE=/var/lib/davarna-autopilot-monitor/state.json"
echo "CRON=/etc/cron.d/davarna-autopilot-monitor"
echo "LOG=/var/log/davarna-autopilot-monitor.log"
echo "NOTE: Monitor is alert-only; never creates, ends, refunds or pays games."
