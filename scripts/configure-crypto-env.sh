#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/davarna}"
BACKEND_ENV="${BACKEND_ENV:-${PROJECT_DIR}/.env.prod}"
BOT_ENV="${BOT_ENV:-${PROJECT_DIR}/davarna-bot/.env.prod}"

die() {
  printf '[configure-crypto-env] ERROR: %s\n' "$*" >&2
  exit 1
}

require_file() {
  [[ -f "$1" ]] || die "environment file not found: $1"
  [[ -r "$1" && -w "$1" ]] || die "environment file is not readable and writable: $1"
}

validate_addresses() {
  [[ -n "${CRYPTO_TRON_USDT_ADDRESS:-}" ]] \
    || die "CRYPTO_TRON_USDT_ADDRESS is required."
  [[ "${CRYPTO_TRON_USDT_ADDRESS}" =~ ^T[1-9A-HJ-NP-Za-km-z]{33}$ ]] \
    || die "CRYPTO_TRON_USDT_ADDRESS is not a valid public TRON address."

  [[ -n "${CRYPTO_TON_ADDRESS:-}" ]] \
    || die "CRYPTO_TON_ADDRESS is required."
  if [[ ! "${CRYPTO_TON_ADDRESS}" =~ ^[A-Za-z0-9_-]{48}$ \
    && ! "${CRYPTO_TON_ADDRESS}" =~ ^-?[0-9]+:[0-9A-Fa-f]{64}$ ]]; then
    die "CRYPTO_TON_ADDRESS is not a valid public TON address."
  fi
}

find_corrupt_values() {
  local file="$1"
  local found=0
  while IFS= read -r line; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    if [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*\?\?.*)$ ]]; then
      printf '[configure-crypto-env] unreadable value must be fixed manually: %s\n' \
        "${BASH_REMATCH[1]}" >&2
      found=1
    fi
  done < "$file"
  return "$found"
}

sanitize_comments() {
  local file="$1"
  local tmp
  tmp="$(mktemp "${file}.tmp.XXXXXX")"
  awk '
    /^[[:space:]]*#/ && index($0, "??") {
      print "# Unreadable legacy comment removed."
      next
    }
    { print }
  ' "$file" > "$tmp"
  chmod --reference="$file" "$tmp"
  chown --reference="$file" "$tmp" 2>/dev/null || true
  mv -f "$tmp" "$file"
}

upsert() {
  local file="$1"
  local key="$2"
  local value="$3"
  local tmp
  tmp="$(mktemp "${file}.tmp.XXXXXX")"
  awk -v wanted="$key" -v replacement="$key=$value" '
    BEGIN { replaced = 0 }
    {
      split($0, parts, "=")
      if ($0 !~ /^[[:space:]]*#/ && parts[1] == wanted) {
        if (!replaced) {
          print replacement
          replaced = 1
        }
        next
      }
      print
    }
    END {
      if (!replaced) {
        print replacement
      }
    }
  ' "$file" > "$tmp"
  chmod --reference="$file" "$tmp"
  chown --reference="$file" "$tmp" 2>/dev/null || true
  mv -f "$tmp" "$file"
}

ensure_default() {
  local file="$1"
  local key="$2"
  local value="$3"
  if ! grep -qE "^${key}=" "$file"; then
    upsert "$file" "$key" "$value"
  fi
}

require_file "$BACKEND_ENV"
require_file "$BOT_ENV"
validate_addresses

find_corrupt_values "$BACKEND_ENV" \
  || die "Fix the listed unreadable values in English, then run this script again."
find_corrupt_values "$BOT_ENV" \
  || die "Fix the listed unreadable values in English, then run this script again."

stamp="$(date +%Y%m%d-%H%M%S)"
cp -a "$BACKEND_ENV" "${BACKEND_ENV}.bak.${stamp}"
cp -a "$BOT_ENV" "${BOT_ENV}.bak.${stamp}"

sanitize_comments "$BACKEND_ENV"
sanitize_comments "$BOT_ENV"

upsert "$BACKEND_ENV" "CRYPTO_PAYMENTS_ENABLED" "true"
upsert "$BACKEND_ENV" "CRYPTO_AUTO_CONFIRM_ENABLED" "true"
upsert "$BACKEND_ENV" "CRYPTO_CONFIRM_INTERVAL_SEC" "45"
upsert "$BACKEND_ENV" "CRYPTO_INVOICE_EXPIRE_MINUTES" "15"
upsert "$BACKEND_ENV" "CRYPTO_PAYMENT_GRACE_MINUTES" "5"
upsert "$BACKEND_ENV" "CRYPTO_PENDING_ALERT_MINUTES" "10"
upsert "$BACKEND_ENV" "CRYPTO_SCAN_LOOKBACK_HOURS" "24"
upsert "$BACKEND_ENV" "CRYPTO_MIN_TOMAN_AMOUNT" "50000"
upsert "$BACKEND_ENV" "CRYPTO_MAX_TOMAN_AMOUNT" "50000000"
upsert "$BACKEND_ENV" "CRYPTO_ADMIN_REVIEW_TOMAN_THRESHOLD" "20000000"
upsert "$BACKEND_ENV" "CRYPTO_DAILY_USER_MAX_COUNT" "5"
upsert "$BACKEND_ENV" "CRYPTO_DAILY_USER_MAX_TOMAN" "100000000"
upsert "$BACKEND_ENV" "CRYPTO_DAILY_TIMEZONE" "Asia/Tehran"
upsert "$BACKEND_ENV" "CRYPTO_RECONCILIATION_LOOKBACK_HOURS" "24"
upsert "$BACKEND_ENV" "CRYPTO_PREFLIGHT_CACHE_SEC" "30"
upsert "$BACKEND_ENV" "CRYPTO_DIRECT_WALLET_PAYMENTS_ENABLED" "true"
upsert "$BACKEND_ENV" "CRYPTO_PUBLIC_APP_URL" "https://davarna.peymoonnet.de"
upsert "$BACKEND_ENV" "CRYPTO_TRON_ESTIMATED_FEE_TRX" "30"
upsert "$BACKEND_ENV" "CRYPTO_TON_ESTIMATED_FEE_TON" "0.01"
upsert "$BACKEND_ENV" "CRYPTO_RATE_PROVIDER_PRIMARY" "nobitex"
upsert "$BACKEND_ENV" "CRYPTO_RATE_PROVIDER_FALLBACK" "wallex"
upsert "$BACKEND_ENV" "CRYPTO_RATE_FAIL_ALLOW_STALE_SEC" "0"
upsert "$BACKEND_ENV" "CRYPTO_RATE_MAX_DEVIATION_PERCENT" "8"
upsert "$BACKEND_ENV" "CRYPTO_RATE_BUFFER_PERCENT" "0"
upsert "$BACKEND_ENV" "CRYPTO_HTTP_TIMEOUT_SEC" "12"
upsert "$BACKEND_ENV" "CRYPTO_BINANCE_BASE_URL" "https://data-api.binance.vision"
upsert "$BACKEND_ENV" "CRYPTO_TRON_USDT_ENABLED" "true"
upsert "$BACKEND_ENV" "CRYPTO_TRON_USDT_ADDRESS" "$CRYPTO_TRON_USDT_ADDRESS"
upsert "$BACKEND_ENV" "CRYPTO_TRON_USDT_CONTRACT" "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
upsert "$BACKEND_ENV" "CRYPTO_TRON_USDT_DECIMALS" "6"
upsert "$BACKEND_ENV" "CRYPTO_TRONGRID_BASE_URL" "https://api.trongrid.io"
upsert "$BACKEND_ENV" "CRYPTO_TRON_EXPLORER_TX_BASE" "https://tronscan.org/#/transaction"
upsert "$BACKEND_ENV" "CRYPTO_TON_ENABLED" "true"
upsert "$BACKEND_ENV" "CRYPTO_TON_ADDRESS" "$CRYPTO_TON_ADDRESS"
upsert "$BACKEND_ENV" "CRYPTO_TON_DECIMALS" "9"
upsert "$BACKEND_ENV" "CRYPTO_TONCENTER_BASE_URL" "https://toncenter.com"
upsert "$BACKEND_ENV" "CRYPTO_TON_EXPLORER_TX_BASE" "https://tonviewer.com/transaction"

if [[ -n "${TRONGRID_API_KEY:-}" ]]; then
  upsert "$BACKEND_ENV" "TRONGRID_API_KEY" "$TRONGRID_API_KEY"
else
  ensure_default "$BACKEND_ENV" "TRONGRID_API_KEY" ""
fi
if [[ -n "${TONCENTER_API_KEY:-}" ]]; then
  upsert "$BACKEND_ENV" "TONCENTER_API_KEY" "$TONCENTER_API_KEY"
else
  ensure_default "$BACKEND_ENV" "TONCENTER_API_KEY" ""
fi
if [[ -n "${CRYPTO_WALLETCONNECT_PROJECT_ID:-}" ]]; then
  upsert "$BACKEND_ENV" "CRYPTO_WALLETCONNECT_PROJECT_ID" "$CRYPTO_WALLETCONNECT_PROJECT_ID"
else
  ensure_default "$BACKEND_ENV" "CRYPTO_WALLETCONNECT_PROJECT_ID" ""
fi

upsert "$BOT_ENV" "ADMIN_CRYPTO_HEALTH_INTERVAL_SEC" "300"
upsert "$BOT_ENV" "ADMIN_CRYPTO_RECONCILIATION_HOUR_LOCAL" "16"

chmod 600 "$BACKEND_ENV" "$BOT_ENV"

printf '[configure-crypto-env] OK\n'
printf '[configure-crypto-env] Updated backend and bot environment files.\n'
printf '[configure-crypto-env] Backups use timestamp: %s\n' "$stamp"
