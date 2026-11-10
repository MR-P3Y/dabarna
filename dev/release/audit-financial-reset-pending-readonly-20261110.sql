-- Davarna financial reset blockers. SELECT-only, no production data changes.
-- Check live statuses and the funded LOW game before any destructive reset.
SELECT 'game_91' AS section, g.id, g.status, g.game_level,
       g.sold_amount, g.commission_amount, g.prize_pool, g.prize_locked,
       (SELECT COUNT(*) FROM game_purchases p WHERE p.game_id=g.id) AS purchases,
       (SELECT COALESCE(SUM(p.total_price),0) FROM game_purchases p WHERE p.game_id=g.id) AS purchase_total,
       (SELECT COUNT(*) FROM game_cards c WHERE c.game_id=g.id) AS cards
 FROM games g WHERE g.id=91;

SELECT 'all_open_game_purchases' AS section, g.id AS game_id,
       g.status, COUNT(p.id) AS purchases,
       COALESCE(SUM(p.total_price),0) AS purchase_total,
       COUNT(DISTINCT p.user_id) AS affected_users
 FROM games g LEFT JOIN game_purchases p ON p.game_id=g.id
 WHERE g.status IN ('LOBBY','RUNNING')
 GROUP BY g.id,g.status ORDER BY g.id;

SELECT 'bank_deposit_status' AS section, status, COUNT(*) AS requests
 FROM deposit_requests GROUP BY status ORDER BY status;

SELECT 'withdrawal_status' AS section, status, COUNT(*) AS requests
 FROM withdraw_requests GROUP BY status ORDER BY status;

SELECT 'gateway_status' AS section, status, COUNT(*) AS payments
 FROM gateway_payments GROUP BY status ORDER BY status;

SELECT 'wallet_ledger_consistency' AS section,
 COUNT(*) AS wallets,
 SUM(CASE WHEN w.balance <> COALESCE(t.net_total,0) THEN 1 ELSE 0 END) AS inconsistent_wallets,
 COALESCE(SUM(w.balance),0) AS balance_total,
 COALESCE(SUM(COALESCE(t.net_total,0)),0) AS ledger_net_total
 FROM wallets w LEFT JOIN (
   SELECT wallet_id, SUM(CASE WHEN direction='CREDIT' THEN amount ELSE -amount END) net_total
   FROM wallet_txs GROUP BY wallet_id
 ) t ON t.wallet_id=w.id;

SELECT 'wallet_ledger_reason_totals' AS section, reason, direction,
 COUNT(*) AS transactions, COALESCE(SUM(amount),0) AS total
 FROM wallet_txs GROUP BY reason,direction ORDER BY reason,direction;

-- If any statement fails due to schema drift, stop and inspect actual schema.
-- No decision to erase historical finance data follows automatically.
