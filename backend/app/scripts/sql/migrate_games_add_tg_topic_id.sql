-- MySQL migration: add Telegram forum topic support to games
-- Run once on production/staging before deploying topic-aware code.

ALTER TABLE games
  ADD COLUMN tg_topic_id BIGINT NULL AFTER tg_group_id;

CREATE INDEX idx_group_topic_status ON games (tg_group_id, tg_topic_id, status);
