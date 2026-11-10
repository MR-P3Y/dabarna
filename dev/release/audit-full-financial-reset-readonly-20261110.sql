-- Davarna production pre-reset census. SELECT ONLY: never zero balances here.
-- Before interpreting the data, distinguish all-test system from real user obligations.
SELECT 'wallet_balances' AS section,
 COUNT(*) AS total_wallets,
 SUM(CASE WHEN balance <> 0 THEN 1 ELSE 0 END) AS nonzero_wallets,
 COALESCE(SUM(balance),0) AS total_balance,
 MIN(balance) AS min_balance, MAX(balance) AS max_balance
FROM wallets;

SELECT 'wallet_ledger_reasons' AS section, reason, direction,
 COUNT(*) AS transaction_count, COALESCE(SUM(amount),0) AS total_amount
FROM wallet_txs GROUP BY reason, direction ORDER BY reason, direction;

SELECT 'active_games' AS section, status, COUNT(*) AS games,
 COALESCE(SUM(sold_amount),0) AS sold_toman,
 COALESCE(SUM(prize_pool),0) AS prize_toman,
 COALESCE(SUM(commission_amount),0) AS commission_toman
FROM games GROUP BY status ORDER BY status;

SELECT 'active_game_finance' AS section, id, status, game_level, game_rule,
 sold_amount, prize_pool, prize_locked, col_paid
FROM games WHERE status IN ('LOBBY','RUNNING')
ORDER BY id DESC;

SELECT 'crypto_requests' AS section, network, status, COUNT(*) AS invoices,
 SUM(wallet_tx_id IS NOT NULL) AS wallet_links, SUM(tx_hash IS NOT NULL) AS hashes
FROM crypto_deposit_requests GROUP BY network,status ORDER BY network,status;

SELECT 'foreign_keys_to_wallets_or_wallet_txs' AS section,
 TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = DATABASE()
 AND REFERENCED_TABLE_NAME IN ('wallets','wallet_txs')
ORDER BY TABLE_NAME,COLUMN_NAME;

SELECT 'financial_related_tables' AS section, TABLE_NAME
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE='BASE TABLE'
 AND (
 TABLE_NAME LIKE '%deposit%' OR TABLE_NAME LIKE '%withdraw%'
 OR TABLE_NAME LIKE '%payment%' OR TABLE_NAME LIKE '%wallet%'
 OR TABLE_NAME LIKE '%prize%' OR TABLE_NAME LIKE '%payout%'
 OR TABLE_NAME LIKE '%game%' OR TABLE_NAME LIKE '%refund%'
 )
ORDER BY TABLE_NAME;

-- Outcome: do not automatically DELETE/UPDATE anything from the counts.
-- A full financial reset also requires explicit downtime, no pending withdrawal
-- or unsettled game, verified restore rehearsal and transactionally consistent
-- audit adjustments. Existing accounts and games must not silently vanish.
