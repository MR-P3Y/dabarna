-- Read-only final guard prior to OPTIONAL cleanout of exactly 20 test invoices.
-- This script MUST NOT delete, update or truncate any rows.
SELECT 'crypto_candidate_count' AS section, COUNT(*) AS total,
       SUM(status IN ('EXPIRED','CANCELLED')) AS closed,
       SUM(status NOT IN ('EXPIRED','CANCELLED')) AS unsafe,
       SUM(tx_hash IS NOT NULL OR paid_amount_crypto IS NOT NULL
           OR detected_at IS NOT NULL OR confirmed_at IS NOT NULL
           OR wallet_tx_id IS NOT NULL OR credited_at IS NOT NULL) AS payment_evidence
FROM crypto_deposit_requests;

SELECT 'cross_ledger_crypto_refs' AS section, COUNT(*) AS linked
FROM wallet_txs w
JOIN crypto_deposit_requests c
 ON (w.ref_type = 'CRYPTO_DEPOSIT' AND w.ref_id = c.id)
 OR (w.idempotency_key = CONCAT('crypto:', c.network, ':', c.tx_hash)
     AND c.tx_hash IS NOT NULL);

SELECT 'crypto_active_user_holds' AS section,
       COUNT(*) AS active_user_references
FROM crypto_deposit_requests WHERE active_user_id IS NOT NULL;

SELECT 'all_crypto_address_totals' AS section, network, destination_address,
       COUNT(*) AS invoice_count, MIN(created_at) AS first_invoice,
       MAX(created_at) AS last_invoice
FROM crypto_deposit_requests GROUP BY network, destination_address
ORDER BY network, destination_address;

-- No output should be interpreted as authorization to delete. Independently
-- verify database snapshot and remote chain history for actual transfers.
