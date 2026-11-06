#!/usr/bin/env bash
# READ-ONLY preflight for a separate UI/UX staging environment.
# No compose up/build, migrations, service restart, data writes or .env loading.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "===== DAVARNA STAGING READ-ONLY PREFLIGHT ====="
printf 'Branch: %s\n' "$(git branch --show-current)"
printf 'Commit: %s\n' "$(git rev-parse --short=12 HEAD)"

if [[ "$(git branch --show-current)" != "feature/ui-ux-refresh-tambola-v2-20261106" ]]; then
  echo "BLOCKER: This preflight must be run from the UI/UX development branch."
  exit 2
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "BLOCKER: Working tree contains uncommitted tracked changes."
  exit 2
fi
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  echo "BLOCKER: Docker daemon is not available."
  exit 2
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "BLOCKER: docker compose is unavailable."
  exit 2
fi

# Show only generic server resource numbers; never read or print credentials.
MEM_AVAILABLE_KIB="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
MEM_TOTAL_KIB="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
SWAP_TOTAL_KIB="$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)"
SWAP_FREE_KIB="$(awk '/^SwapFree:/ {print $2}' /proc/meminfo)"
DISK_AVAILABLE_KIB="$(df -Pk "$ROOT" | awk 'NR == 2 {print $4}')"
[[ "$MEM_AVAILABLE_KIB" =~ ^[0-9]+$ ]] || { echo "BLOCKER: Unknown available RAM"; exit 2; }
[[ "$DISK_AVAILABLE_KIB" =~ ^[0-9]+$ ]] || { echo "BLOCKER: Unknown available disk"; exit 2; }
SWAP_TOTAL_KIB="${SWAP_TOTAL_KIB:-0}"
SWAP_FREE_KIB="${SWAP_FREE_KIB:-0}"
SWAP_USED_KIB=$((SWAP_TOTAL_KIB - SWAP_FREE_KIB))

echo "===== HOST RESOURCES ====="
printf 'RAM total: %s MiB\n' "$((MEM_TOTAL_KIB / 1024))"
printf 'RAM available: %s MiB\n' "$((MEM_AVAILABLE_KIB / 1024))"
printf 'Swap used: %s MiB\n' "$((SWAP_USED_KIB / 1024))"
printf 'Disk available at checkout: %s MiB\n' "$((DISK_AVAILABLE_KIB / 1024))"

echo "===== RUNNING CONTAINERS (NAMES/STATUS ONLY) ====="
docker ps --format 'table {{.Names}}\t{{.Status}}'

echo "===== STAGING PORT CHECK ====="
PORT="${DAVARNA_STAGE_PORT:-18190}"
if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1024 || PORT > 65535 )); then
  echo "BLOCKER: Invalid staging port."
  exit 2
fi
if ss -ltnH "( sport = :${PORT} )" | grep -q .; then
  echo "BLOCKER: Candidate loopback port ${PORT} is already in use."
  exit 2
fi
printf 'Port %s: available (not opened)\n' "$PORT"

echo "===== ISOLATION AUDIT ====="
if grep -q 'container_name: davarna-' docker-compose.yml; then
  echo "BLOCKER: Root docker-compose.yml has fixed production-style container names."
  echo "Do NOT run it as staging, even with another Compose project name."
else
  echo "Root Compose names: no fixed davarna-* names detected."
fi
if grep -Eq '(\.env\.prod|BACKEND_ENV_FILE|BOT_ENV_FILE)' docker-compose.yml; then
  echo "BLOCKER: Root Compose references production environment files by default."
  echo "Staging requires a separate Compose file and standalone non-production credentials."
fi

echo "===== RESOURCE GATE ====="
# Conservative gate for an additional database, backend and build on a production host.
MIN_RAM_KIB=$((2560 * 1024))
MIN_DISK_KIB=$((6144 * 1024))
WARNINGS=0
if (( MEM_AVAILABLE_KIB < MIN_RAM_KIB )); then
  echo "BLOCKER: Available RAM below 2560 MiB. Prefer a separate staging VPS."
  WARNINGS=$((WARNINGS + 1))
fi
if (( DISK_AVAILABLE_KIB < MIN_DISK_KIB )); then
  echo "BLOCKER: Available disk below 6 GiB."
  WARNINGS=$((WARNINGS + 1))
fi
if (( SWAP_TOTAL_KIB > 0 && SWAP_USED_KIB * 100 / SWAP_TOTAL_KIB >= 50 )); then
  echo "WARNING: Swap is at least 50% used; investigate memory pressure first."
  WARNINGS=$((WARNINGS + 1))
fi

echo "===== VERDICT ====="
if (( WARNINGS > 0 )); then
  echo "NO-GO: Do not start staging on this host until capacity issues are addressed."
  exit 2
fi
echo "CAPACITY PREFLIGHT PASSED, but staging is NOT authorized or started."
echo "Separate database, isolated network, dummy payment credentials, and test Telegram bot are still required."
