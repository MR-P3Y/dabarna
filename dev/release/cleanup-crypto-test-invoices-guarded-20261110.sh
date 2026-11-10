#!/usr/bin/env bash
# Remove exactly 20 proven test-only CLOSED crypto invoices after a local backup.
# Production: explicit operator approval required. No wallet/ledger mutations.
set -Eeuo pipefail
umask 077
APPROVAL="${1:-}"
if [[ "$APPROVAL" != "DELETE_20_CLOSED_CRYPTO_TEST_INVOICES" ]]; then
  echo "Dry-run only. To authorize after review, pass DELETE_20_CLOSED_CRYPTO_TEST_INVOICES"
  exit 2
fi
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
# No mutation to production while the crypto payments feature is active.
runtime="$(query "SELECT COALESCE(JSON_UNQUOTE(JSON_EXTRACT(v_json, '$.enabled')), JSON_UNQUOTE(v_json)) FROM app_settings WHERE k='crypto_payments_runtime_enabled' LIMIT 1;" || true)"
case "${runtime,,}" in
  true|1|yes|on) echo "BLOCKED: crypto payments are enabled"; exit 3;;
esac
# All 20 must be expired/cancelled with zero signs of real-chain settlement.
count="$(get_count "SELECT COUNT(*) FROM crypto_deposit_requests;")"
unsafe="$(get_count "SELECT COUNT(*) FROM crypto_deposit_requests WHERE status NOT IN ('EXPIRED','CANCELLED') OR tx_hash IS NOT NULL OR paid_amount_crypto IS NOT NULL OR detected_at IS NOT NULL OR confirmed_at IS NOT NULL OR wallet_tx_id IS NOT NULL OR credited_at IS NOT NULL OR active_user_id IS NOT NULL;")"
links="$(get_count "SELECT COUNT(*) FROM wallet_txs WHERE reason='DEPOSIT_CRYPTO' OR ref_type='CRYPTO_DEPOSIT' OR idempotency_key LIKE 'crypto:%';")"
[[ "$count" == 20 && "$unsafe" == 0 && "$links" == 0 ]] || {
  echo "BLOCKED: expected 20 closed invoices, zero evidence/links; got count=$count unsafe=$unsafe ledger=$links"; exit 3;
}
# Full logical database backup: never erase or rewrite user's wallet balances.
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dir="/root/davarna-v2-release-backups/crypto-test-cleanup-$stamp"
mkdir -p -m 700 "$dir"
echo "===== BACKUP DATABASE ====="
"${DC[@]}" exec -T mysql sh -lc 'exec mysqldump --single-transaction --quick --no-tablespaces -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' > "$dir/full-database.sql"
test -s "$dir/full-database.sql" || { echo "BLOCKED: empty backup"; exit 4; }
sha256sum "$dir/full-database.sql" > "$dir/SHA256SUMS"
echo "Backup complete: $dir"
# Captures wallet balance invariant without changing existing wallets.
before="$(query 'SELECT CONCAT(COUNT(*),":",COALESCE(SUM(balance),0)) FROM wallets WHERE balance<>0;' | tr -d '\r\n')"
# Transactional guard: locks all rows and rolls back if any expected condition fails.
# Single SQL connection: no separate pre-check can authorize partial mutation.
read -r -d '' sql <<'SQL' || true
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
START TRANSACTION;
SELECT id FROM crypto_deposit_requests ORDER BY id FOR UPDATE;
SET @n := (SELECT COUNT(*) FROM crypto_deposit_requests);
SET @bad := (SELECT COUNT(*) FROM crypto_deposit_requests
 WHERE status NOT IN ('EXPIRED','CANCELLED')
 OR tx_hash IS NOT NULL OR paid_amount_crypto IS NOT NULL
 OR detected_at IS NOT NULL OR confirmed_at IS NOT NULL
 OR wallet_tx_id IS NOT NULL OR credited_at IS NOT NULL
 OR active_user_id IS NOT NULL);
SET @ledgers := (SELECT COUNT(*) FROM wallet_txs
 WHERE reason='DEPOSIT_CRYPTO' OR ref_type='CRYPTO_DEPOSIT'
 OR idempotency_key LIKE 'crypto:%');
DELETE FROM crypto_deposit_requests
 WHERE @n=20 AND @bad=0 AND @ledgers=0
 AND status IN ('EXPIRED','CANCELLED')
 AND tx_hash IS NULL AND paid_amount_crypto IS NULL
 AND detected_at IS NULL AND confirmed_at IS NULL
 AND wallet_tx_id IS NULL AND credited_at IS NULL
 AND active_user_id IS NULL;
SET @deleted := ROW_COUNT();
-- If fewer than 20 were deleted this will return an error, disconnecting
-- the mysql CLI and rolling back this uncommitted transaction.
SET @must_be_20 := IF(@deleted=20, 1, NULL);
SET @checked := (SELECT @must_be_20 + 1);
COMMIT;
SELECT @deleted AS deleted_invoices;
SQL
# MySQL 'SELECT NULL' is not an exception, so use an explicit verified
# stored-program assertion below instead of trusting the SQL above.
echo "BLOCKED: deletion SQL is a draft; no DELETE was executed."
echo "Backup remains at: $dir"
echo "Wallet baseline: $before"
exit 5
