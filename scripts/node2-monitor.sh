#!/usr/bin/env bash
set -euo pipefail
umask 077

APP_DIR="${APP_DIR:-/opt/davarna}"
LOG_DIR="${LOG_DIR:-/var/log/davarna}"
STATE_DIR="${STATE_DIR:-/var/lib/davarna-monitor}"
LOG_FILE="${LOG_DIR}/monitor.log"
ENV_FILE="${APP_DIR}/.env.prod"

DISK_WARN=80
MEM_WARN=85
SWAP_WARN=90
BACKUP_MAX_AGE_SECONDS=50400  # 14 hours
COOLDOWN_SECONDS=3600         # avoid Telegram spam

mkdir -p "$LOG_DIR" "$STATE_DIR"
exec 9>"${STATE_DIR}/run.lock"
flock -n 9 || exit 0

log() {
  echo "[$(date -Is)] $*" >> "$LOG_FILE"
}

read_env_value() {
  local key="$1"
  awk -F= -v k="$key" '$1 == k {sub(/^[^=]*=/, ""); gsub(/^["'\''"]|["'\''"]$/, ""); print; exit}' "$ENV_FILE"
}

send_telegram() {
  local text="$1"
  local bot_token chat_id

  bot_token="$(read_env_value BACKUP_BOT_TOKEN)"
  if [[ -z "${bot_token}" ]]; then
    bot_token="$(read_env_value TELEGRAM_BOT_TOKEN)"
  fi
  chat_id="$(read_env_value BACKUP_CHAT_ID)"

  if [[ -z "${bot_token}" || -z "${chat_id}" ]]; then
    log "telegram skipped: missing BACKUP_BOT_TOKEN/TELEGRAM_BOT_TOKEN or BACKUP_CHAT_ID"
    return 1
  fi

  curl --fail --silent --max-time 15 \
    -X POST "https://api.telegram.org/bot${bot_token}/sendMessage" \
    -d "chat_id=${chat_id}" \
    --data-urlencode "text=${text}" \
    >/dev/null 2>&1 || { log "telegram send failed; retry remains pending"; return 1; }
}

ISSUES=()

disk_pct="$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}')"
if (( disk_pct >= DISK_WARN )); then
  ISSUES+=("Disk usage is ${disk_pct}% on /")
fi

mem_pct="$(free | awk '/Mem:/ {printf "%.0f", (($2-$7)/$2)*100}')"
if (( mem_pct >= MEM_WARN )); then
  ISSUES+=("Memory usage is ${mem_pct}%")
fi

swap_pct="$(free | awk '/Swap:/ {if ($2 == 0) print 0; else printf "%.0f", ($3/$2)*100}')"
if (( swap_pct >= SWAP_WARN )); then
  ISSUES+=("Swap usage >= ${SWAP_WARN}%")
fi

if ! curl -fsS --max-time 10 "http://127.0.0.1:18080/health/db" >/dev/null; then
  ISSUES+=("Davarna health/db failed")
fi

check_container() {
  local name="$1"
  local require_health="$2"
  local state health

  if ! sudo docker inspect "$name" >/dev/null 2>&1; then
    ISSUES+=("Container missing: ${name}")
    return
  fi

  state="$(sudo docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || echo false)"
  health="$(sudo docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-health{{end}}' "$name" 2>/dev/null || echo unknown)"

  if [[ "$state" != "true" ]]; then
    ISSUES+=("Container not running: ${name}")
    return
  fi

  if [[ "$require_health" == "yes" && "$health" != "healthy" ]]; then
    ISSUES+=("Container not healthy: ${name} health=${health}")
  fi
}

check_container "davarna-backend" "yes"
check_container "davarna-mysql" "yes"
check_container "davarna-redis" "yes"
check_container "davarna-bot" "no"

latest_backup="$(sudo find /root/davarna_backups/mysql -type f -name 'davarna_mysql_*.sql.gz' -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2- || true)"
if [[ -z "$latest_backup" ]]; then
  ISSUES+=("No local MySQL backup found")
else
  now="$(date +%s)"
  backup_mtime="$(sudo stat -c %Y "$latest_backup")"
  backup_age=$((now - backup_mtime))
  if (( backup_age > BACKUP_MAX_AGE_SECONDS )); then
    ISSUES+=("Latest local MySQL backup is older than 14 hours: ${latest_backup}")
  fi
fi

# Compare stable issue identities, never timestamps, percentages or backup filenames.
ISSUE_FILE="${STATE_DIR}/current_issues.txt"
LAST_SENT_FILE="${STATE_DIR}/last_sent_at"
PREVIOUS_FILE="${STATE_DIR}/previous_issues.txt"
FINGERPRINT_FILE="${STATE_DIR}/last_sent_fingerprint"

fingerprint() {
  sed -E '/^(Time:|Davarna monitor ALERT|[[:space:]]*$)/d; s/Disk usage is [0-9]+% on \//Disk pressure/; s/Memory usage is [0-9]+%/Memory pressure/; s/Swap usage.*/Swap pressure/; s/Latest local MySQL backup is older than 14 hours:.*/Backup overdue/' | LC_ALL=C sort -u | sha256sum | cut -d' ' -f1
}

atomic_write() {
  local destination="$1" value="$2"
  printf '%s\n' "$value" > "${destination}.tmp"
  mv -f "${destination}.tmp" "$destination"
}

last_sent=0
[[ -f "$LAST_SENT_FILE" ]] && last_sent="$(cat "$LAST_SENT_FILE")"
[[ "$last_sent" =~ ^[0-9]+$ ]] || last_sent=0
now="$(date +%s)"
previous=""
if [[ -s "$FINGERPRINT_FILE" ]]; then
  previous="$(cat "$FINGERPRINT_FILE")"
elif [[ -s "$PREVIOUS_FILE" ]]; then
  # Carry over the old monitor's latest state without replaying an unchanged alert.
  previous="$(fingerprint < "$PREVIOUS_FILE")"
fi

if (( ${#ISSUES[@]} == 0 )); then
  current="$(printf 'OK\n' | fingerprint)"
  atomic_write "$ISSUE_FILE" "OK"
  if [[ -z "$previous" || "$previous" == "$current" ]]; then
    atomic_write "$FINGERPRINT_FILE" "$current"
  elif send_telegram "Davarna monitor OK: all checks recovered on $(hostname)"; then
    atomic_write "$FINGERPRINT_FILE" "$current"
    atomic_write "$LAST_SENT_FILE" "$now"
    atomic_write "$PREVIOUS_FILE" "OK"
  fi
  log "ok disk=${disk_pct}% mem=${mem_pct}% swap=${swap_pct}%"
  exit 0
fi

current="$(printf '%s\n' "${ISSUES[@]}" | fingerprint)"
message="$(printf 'Davarna monitor ALERT on %s\nTime: %s\n\n' "$(hostname)" "$(date -Is)"; printf '%s\n' "${ISSUES[@]}")"
atomic_write "$ISSUE_FILE" "$message"
if [[ "$current" != "$previous" ]] || (( now - last_sent >= COOLDOWN_SECONDS )); then
  if send_telegram "$message"; then
    # ACK only a successful request; failed sends are retried on the next scan.
    atomic_write "$FINGERPRINT_FILE" "$current"
    atomic_write "$LAST_SENT_FILE" "$now"
    atomic_write "$PREVIOUS_FILE" "$message"
  fi
fi
log "alert count=${#ISSUES[@]}"
