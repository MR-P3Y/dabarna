-- Davarna crypto-history audit, READ ONLY. Never delete financial history
-- just because it was described as a test. Run with a read-only MySQL user.
-- Keep this report and verified database backup before any authorized cleanup.
SELECT 'crypto_by_network_status' AS section, network, status,
       COUNT(*) AS invoice_count, COALESCE(SUM(amount_toman),0) AS quoted_toman,
       SUM(CASE WHEN tx_hash IS NOT NULL THEN 1 ELSE 0 END) AS claimed_hashes,
       SUM(CASE WHEN wallet_tx_id IS NOT NULL THEN 1 ELSE 0 END) AS linked_wallet_txs,
       SUM(CASE WHEN detected_at IS NOT NULL OR confirmed_at IS NOT NULL THEN 1 ELSE 0 END) AS detected_transfers
  FROM crypto_deposit_requests
 GROUP BY network,status ORDER BY network,status;

SELECT 'risk_summary' AS section,
       COUNT(*) AS total_invoices,
       COALESCE(SUM(CASE WHEN status IN ('WAITING_PAYMENT','CONFIRMING','NEEDS_REVIEW') THEN 1 ELSE 0 END),0) AS unsettled_invoices,
       COALESCE(SUM(CASE WHEN status = 'CREDITED' THEN 1 ELSE 0 END),0) AS credited_invoices,
       COALESCE(SUM(CASE WHEN tx_hash IS NOT NULL OR detected_at IS NOT NULL OR confirmed_at IS NOT NULL
                           OR paid_amount_crypto IS NOT NULL THEN 1 ELSE 0 END),0) AS chain_evidence_invoices,
       COALESCE(SUM(CASE WHEN wallet_tx_id IS NOT NULL THEN 1 ELSE 0 END),0) AS wallet_linked_invoices
  FROM crypto_deposit_requests;

SELECT 'ledger_crypto' AS section, COUNT(*) AS ledger_rows,
       COALESCE(SUM(CASE WHEN direction = 'CREDIT' THEN amount ELSE 0 END),0) AS credit_toman,
       COALESCE(SUM(CASE WHEN direction = 'DEBIT' THEN amount ELSE 0 END),0) AS debit_toman
  FROM wallet_txs WHERE reason = 'DEPOSIT_CRYPTO'
    OR ref_type = 'CRYPTO_DEPOSIT'
    OR idempotency_key LIKE 'crypto:%';

SELECT 'orphan_crypto_ledger' AS section, COUNT(*) AS ledger_without_matching_invoice
  FROM wallet_txs w
  LEFT JOIN crypto_deposit_requests i
    ON w.ref_type='CRYPTO_DEPOSIT' AND w.ref_id=i.id
 WHERE (w.reason='DEPOSIT_CRYPTO' OR w.ref_type='CRYPTO_DEPOSIT'
        OR w.idempotency_key LIKE 'crypto:%')
   AND i.id IS NULL;

SELECT 'wallets_with_nonzero_balance' AS section, COUNT(*) AS wallet_count,
       COALESCE(SUM(balance),0) AS total_balance
  FROM wallets WHERE balance <> 0;

-- Test status is not a column here: infer nothing about whether any row
-- contains real money. Wallet and invoice deletions must not be automated.
