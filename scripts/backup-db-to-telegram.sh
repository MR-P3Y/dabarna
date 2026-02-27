#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f .env.prod ]]; then
  echo ".env.prod not found in ${ROOT_DIR}" >&2
  exit 1
fi

read_env_value() {
  local file="$1"
  local key="$2"
  [[ -f "${file}" ]] || return 0
  awk -F= -v k="${key}" '$1 == k {sub(/^[^=]*=/, ""); sub(/\r$/, ""); print; exit}' "${file}"
}

CHAT_ID="$(read_env_value ./.env.prod BACKUP_CHAT_ID)"
BACKUP_BOT_TOKEN_VALUE="$(read_env_value ./.env.prod BACKUP_BOT_TOKEN)"
ROOT_BOT_TOKEN_VALUE="$(read_env_value ./.env.prod TELEGRAM_BOT_TOKEN)"
BOT_ENV_BOT_TOKEN_VALUE="$(read_env_value ./davarna-bot/.env.prod TELEGRAM_BOT_TOKEN)"

BOT_TOKEN="${BACKUP_BOT_TOKEN_VALUE:-${ROOT_BOT_TOKEN_VALUE:-${BOT_ENV_BOT_TOKEN_VALUE:-}}}"

if [[ -z "${BOT_TOKEN}" ]]; then
  echo "Missing bot token. Set BACKUP_BOT_TOKEN or TELEGRAM_BOT_TOKEN in .env.prod" >&2
  exit 1
fi

if [[ -z "${CHAT_ID}" ]]; then
  echo "Missing BACKUP_CHAT_ID in .env.prod" >&2
  exit 1
fi

STAMP="$(date -u +%Y%m%d_%H%M%S)"
FILENAME="davarna_mysql_${STAMP}.sql.gz"
CAPTION="Davarna DB backup ${STAMP} UTC"

docker compose --env-file .env.prod exec -T mysql sh -c \
  'exec mysqldump --single-transaction --quick --routines --triggers --no-tablespaces -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
  | gzip -c \
  | curl --fail --silent --show-error \
    -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendDocument" \
    -F "chat_id=${CHAT_ID}" \
    -F "caption=${CAPTION}" \
    -F "document=@-;filename=${FILENAME};type=application/gzip" \
    > /dev/null

echo "Backup sent to chat ${CHAT_ID}: ${FILENAME}"
