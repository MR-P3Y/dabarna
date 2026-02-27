-- MySQL migration: expand game_events.kind enum for new row/col payout model
-- Run manually on production database before enabling strict PRIZE_COL/PRIZE_ROW usage.

ALTER TABLE game_events
MODIFY COLUMN kind ENUM(
  'GAME_CREATED',
  'CARDS_PURCHASED',
  'GAME_STARTED',
  'GAME_START_REJECTED',
  'NUMBER_CALLED',
  'NUMBER_UNDONE',
  'PRIZE_COL',
  'PRIZE_ROW',
  'GAME_ENDED',
  'GAME_LOBBY_CLOSED',
  'ERROR'
) NOT NULL;
