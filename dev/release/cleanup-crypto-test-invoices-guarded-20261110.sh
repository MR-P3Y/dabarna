#!/usr/bin/env bash
# READ-ONLY pre-cleanup audit and backup. No data deletion in this script.
set -Eeuo pipefail
umask 077
PROD=/opt/davarna
DC=(docker compose --project-directory "$PROD" -f "$PROD/docker-compose.yml" --env-file "$PROD/.env.prod")
[[ -f "$PROD/.env.prod" ]] || { echo "Missing production env"; exit 2; }
[[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-mysql)" == healthy ]] || {
  echo "MySQL is not healthy"; exit 2;
}
mysql_cmd() {
  "${DC[@]}" exec -T mysql sh -lc 'exec mysql --batch --skip-column-names -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
}
query() { printf '%s\n' "$1" | mysql_cmd; }
get_count() {
  local value
  value="$(query "$1" | tr -d '\r\n')"
  [[ "$value" =~ ^[0-9]+$ ]] || { echo "Non-numeric check result"; exit 3; }
  printf '%s' "$value"
}
echo "===== VERIFY EXACT CLOSED INVOICE SET ====="
count="$(get_count 'SELECT COUNT(*) FROM crypto_deposit_requests;')"
unsafe="$(get_count "SELECT COUNT(*) FROM crypto_deposit_requests WHERE status NOT IN ('EXPIRED','CANCELLED') OR tx_hash IS NOT NULL OR paid_amount_crypto IS NOT NULL OR detected_at IS NOT NULL OR confirmed_at IS NOT NULL OR wallet_tx_id IS NOT NULL OR credited_at IS NOT NULL OR active_user_id IS NOT NULL;")"
links="$(get_count "SELECT COUNT(*) FROM wallet_txs WHERE reason='DEPOSIT_CRYPTO' OR ref_type='CRYPTO_DEPOSIT' OR idempotency_key LIKE 'crypto:%';")"
echo "Invoices=$count Unsafe=$unsafe CryptoLedger=$links"
[[ "$count" == 20 && "$unsafe" == 0 && "$links" == 0 ]] || {
  echo "BLOCKED: population changed, no cleanup eligible"; exit 3;
}
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dir="/root/davarna-v2-release-backups/crypto-test-cleanup-$stamp"
mkdir -p -m 700 "$dir"
echo "===== BACKUP DATABASE ====="
"${DC[@]}" exec -T mysql sh -lc 'exec mysqldump --single-transaction --quick --no-tablespaces -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' > "$dir/full-database.sql"
test -s "$dir/full-database.sql" || { echo "BLOCKED: empty backup"; exit 4; }
sha256sum "$dir/full-database.sql" > "$dir/SHA256SUMS"
echo "===== VERIFY RESTORE ARTIFACT ====="
ls -lh "$dir/full-database.sql"
cat "$dir/SHA256SUMS"
echo "Backup location: $dir"
echo "READ-ONLY PREPARATION COMPLETE; NO ROWS WERE DELETED."
