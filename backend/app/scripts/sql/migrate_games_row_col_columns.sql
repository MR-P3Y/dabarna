-- MySQL migration: rename game payout columns from line/full to col/row

ALTER TABLE games
  RENAME COLUMN line_prize_amount TO col_prize_amount,
  RENAME COLUMN full_prize_amount TO row_prize_amount,
  RENAME COLUMN line_paid TO col_paid,
  RENAME COLUMN line_winners_json TO payout_state_json,
  RENAME COLUMN full_winner_user_id TO row_winner_user_id;

