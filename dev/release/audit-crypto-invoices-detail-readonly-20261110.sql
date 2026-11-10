-- READ ONLY: detailed inventory of historical TON/TRON invoices for reconciliation.
-- Run against Production using a SELECT-only MySQL account where possible.
-- This script never writes, deletes, credits, or changes invoice/wallet state.
-- User IDs are included only to support private reconciliation; do not publish output.
SET SESSION TRANSACTION READ ONLY;
START TRANSACTION READ ONLY;

SELECT
    'invoice_detail' AS section,
    c.id AS invoice_id,
    c.public_id,
    c.user_id,
    c.network,
    c.asset,
    c.status,
    c.amount_toman,
    c.amount_crypto AS requested_crypto,
    c.paid_amount_crypto,
    c.destination_address,
    c.memo,
    c.tx_hash,
    c.sender_address,
    c.wallet_provider,
    c.wallet_account_address,
    c.payment_variance,
    c.variance_amount_crypto,
    c.confirmation_count,
    c.required_confirmations,
    c.failure_reason,
    c.created_at,
    c.expires_at,
    c.payment_requested_at,
    c.detected_at,
    c.confirmed_at,
    c.credited_at,
    c.cancelled_at,
    c.last_checked_at,
    c.wallet_tx_id,
    wtx.wallet_id,
    wtx.direction AS ledger_direction,
    wtx.amount AS ledger_amount_toman,
    wtx.reason AS ledger_reason,
    wtx.ref_type AS ledger_ref_type,
    wtx.ref_id AS ledger_ref_id,
    wtx.idempotency_key AS ledger_idempotency_key,
    wtx.created_at AS ledger_created_at
FROM crypto_deposit_requests c
LEFT JOIN wallet_txs wtx ON wtx.id = c.wallet_tx_id
WHERE c.network IN ('TRON', 'TON')
  AND c.status IN ('EXPIRED', 'CANCELLED', 'REJECTED',
                   'WAITING_PAYMENT', 'CONFIRMING', 'NEEDS_REVIEW', 'CREDITED')
ORDER BY c.network, c.destination_address, c.created_at, c.id;

SELECT
    'invoice_evidence_summary' AS section,
    c.network,
    c.status,
    COUNT(*) AS invoice_count,
    SUM(c.tx_hash IS NOT NULL) AS has_tx_hash,
    SUM(c.sender_address IS NOT NULL) AS has_sender_address,
    SUM(c.paid_amount_crypto IS NOT NULL) AS has_paid_amount,
    SUM(c.detected_at IS NOT NULL) AS has_detected_at,
    SUM(c.confirmed_at IS NOT NULL) AS has_confirmed_at,
    SUM(c.credited_at IS NOT NULL) AS has_credited_at,
    SUM(c.wallet_tx_id IS NOT NULL) AS has_wallet_tx_link,
    SUM(c.memo IS NOT NULL AND c.memo <> '') AS has_memo
FROM crypto_deposit_requests c
WHERE c.network IN ('TRON', 'TON')
GROUP BY c.network, c.status
ORDER BY c.network, c.status;

SELECT
    'crypto_ledger_references' AS section,
    wtx.id AS wallet_tx_id,
    wtx.wallet_id,
    wtx.direction,
    wtx.amount,
    wtx.reason,
    wtx.ref_type,
    wtx.ref_id,
    wtx.idempotency_key,
    wtx.created_at,
    c.id AS matching_invoice_id,
    c.network AS matching_network,
    c.tx_hash AS matching_tx_hash
FROM wallet_txs wtx
LEFT JOIN crypto_deposit_requests c
  ON (wtx.ref_type = 'CRYPTO_DEPOSIT' AND wtx.ref_id = c.id)
  OR (c.wallet_tx_id = wtx.id)
WHERE wtx.reason = 'DEPOSIT_CRYPTO'
   OR wtx.ref_type = 'CRYPTO_DEPOSIT'
   OR wtx.idempotency_key LIKE 'crypto:%'
ORDER BY wtx.created_at, wtx.id;

COMMIT;
