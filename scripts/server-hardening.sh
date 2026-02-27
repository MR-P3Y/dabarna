#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/davarna"
SWAP_FILE="/swapfile"
SWAP_SIZE_GB="${SWAP_SIZE_GB:-2}"
TARGET_TZ="${TARGET_TZ:-Asia/Tehran}"

if [[ ! -d "${PROJECT_DIR}" ]]; then
  echo "Project directory not found: ${PROJECT_DIR}" >&2
  exit 1
fi

echo "[1/5] Configure host timezone (${TARGET_TZ})..."
if command -v timedatectl >/dev/null 2>&1; then
  timedatectl set-timezone "${TARGET_TZ}"
else
  ln -snf "/usr/share/zoneinfo/${TARGET_TZ}" /etc/localtime
fi
echo "${TARGET_TZ}" > /etc/timezone

echo "[2/5] Configure swap (${SWAP_SIZE_GB}G)..."
if ! swapon --show | grep -q "${SWAP_FILE}"; then
  if command -v fallocate >/dev/null 2>&1; then
    fallocate -l "${SWAP_SIZE_GB}G" "${SWAP_FILE}"
  else
    dd if=/dev/zero of="${SWAP_FILE}" bs=1M count=$((SWAP_SIZE_GB * 1024)) status=progress
  fi
  chmod 600 "${SWAP_FILE}"
  mkswap "${SWAP_FILE}"
  swapon "${SWAP_FILE}"
fi

grep -q "^${SWAP_FILE}" /etc/fstab || echo "${SWAP_FILE} none swap sw 0 0" >> /etc/fstab

cat > /etc/sysctl.d/99-davarna-swap.conf <<EOF
vm.swappiness=20
vm.vfs_cache_pressure=50
EOF
sysctl --system >/dev/null

echo "[3/5] Configure cron jobs..."
chmod +x "${PROJECT_DIR}/scripts/backup-db-to-telegram.sh" "${PROJECT_DIR}/scripts/cleanup-receipts.sh"

cat > /etc/cron.d/davarna-maintenance <<'EOF'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CRON_TZ=Asia/Tehran
# Daily DB backup to Telegram at 01:30 Tehran time
30 1 * * * root cd /opt/davarna && /opt/davarna/scripts/backup-db-to-telegram.sh >> /var/log/davarna-backup.log 2>&1
# Daily cleanup for receipt files older than 5 days at 02:00 Tehran time
0 2 * * * root cd /opt/davarna && /opt/davarna/scripts/cleanup-receipts.sh >> /var/log/davarna-cleanup.log 2>&1
EOF

chmod 644 /etc/cron.d/davarna-maintenance
touch /var/log/davarna-backup.log /var/log/davarna-cleanup.log

if command -v systemctl >/dev/null 2>&1; then
  if systemctl list-unit-files | grep -q '^cron\.service'; then
    systemctl enable --now cron >/dev/null 2>&1 || true
  fi
fi

echo "[4/5] Configure UFW rules..."
if ! command -v ufw >/dev/null 2>&1; then
  apt-get update -y >/dev/null
  apt-get install -y ufw >/dev/null
fi

ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp comment 'ssh' >/dev/null
ufw allow 80/tcp comment 'http' >/dev/null
ufw allow 443/tcp comment 'https' >/dev/null
ufw allow 2053/tcp comment 'x-ui-panel' >/dev/null
ufw allow 5678/tcp comment 'n8n' >/dev/null
ufw allow 1356/tcp comment 'x-ui-inbound-1356' >/dev/null
ufw allow 1357/tcp comment 'x-ui-inbound-1357' >/dev/null
ufw --force enable >/dev/null

echo "[5/5] Status summary..."
timedatectl status | sed -n '1,12p' || true
echo "---"
free -h
echo "---"
swapon --show
echo "---"
ufw status verbose
echo "---"
systemctl is-enabled cron 2>/dev/null || true
systemctl is-active cron 2>/dev/null || true
