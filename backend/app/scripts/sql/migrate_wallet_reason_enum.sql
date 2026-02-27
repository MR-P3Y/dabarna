-- MySQL migration: update wallet_txs.reason enum for row/col payouts

UPDATE wallet_txs SET reason = 'PRIZE_COL' WHERE reason = 'PRIZE_LINE';
UPDATE wallet_txs SET reason = 'PRIZE_ROW' WHERE reason = 'PRIZE_FULL';

ALTER TABLE wallet_txs
MODIFY COLUMN reason ENUM(
  'DEPOSIT_MANUAL',
  'DEPOSIT_GATEWAY',
  'BUY_CARDS',
  'PRIZE_COL',
  'PRIZE_ROW',
  'WITHDRAW',
  'ADJUST'
) NOT NULL;

