#!/usr/bin/env bash
# Read-only readiness report for Davarna Tambola V2.
# Run: bash scripts/tambola-v2-preflight.sh
set -Eeuo pipefail

ROOT="/opt/davarna"
if [[ ! -r "${ROOT}/.env.prod" || ! -f "${ROOT}/docker-compose.yml" ]]; then
  echo "FAIL: production compose/env not found in ${ROOT}" >&2
  exit 1
fi

cd "${ROOT}"
echo "===== PRODUCTION GIT ====="
git branch --show-current
git rev-parse --short HEAD
git status -sb

echo "===== LIVE CONTAINERS ====="
docker compose --env-file .env.prod ps backend bot mysql redis

echo "===== FEATURE FLAGS (FROM RUNNING BACKEND) ====="
docker compose --env-file .env.prod exec -T backend python -c '
from app.core import config as c
for name in ("GAME_TAMBOLA_V2_ENABLED", "GAME_AUTOPILOT_RUNTIME_ENABLED"):
    value = getattr(c, name, "NOT_DEFINED_IN_RUNNING_VERSION")
    print(f"{name}={value}")
'

echo "===== PRODUCTION DB (READ ONLY) ====="
docker compose --env-file .env.prod exec -T mysql sh -lc \
  'exec mysql -N -B -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' <<'SQL'
SELECT 'database', DATABASE();
SELECT 'migration', version_num FROM alembic_version;
SELECT 'all_games', COUNT(*) FROM games;
SELECT 'v2_games', COUNT(*) FROM games WHERE card_layout_version=2;
SELECT 'running_games', COUNT(*) FROM games WHERE status='RUNNING';
SELECT 'lobby_games', COUNT(*) FROM games WHERE status='LOBBY';
SELECT 'wallets_count', COUNT(*) FROM wallets;
SELECT 'wallets_balance_total', COALESCE(SUM(balance),0) FROM wallets;
SELECT 'wallet_transactions_count', COUNT(*) FROM wallet_txs;
SELECT 'purchases_count', COUNT(*) FROM game_purchases;
SELECT 'cards_count', COUNT(*) FROM game_cards;
SELECT 'wallet_ledger_balance_mismatch_count', COUNT(*)
FROM wallets w LEFT JOIN (
  SELECT wallet_id,
         SUM(CASE WHEN direction='CREDIT' THEN amount ELSE -amount END) AS net
  FROM wallet_txs GROUP BY wallet_id
) t ON t.wallet_id=w.id
WHERE w.balance<>COALESCE(t.net,0);
SELECT 'orphan_purchase_tx_count', COUNT(*)
FROM game_purchases p
LEFT JOIN wallet_txs t ON t.id=p.wallet_tx_id
WHERE t.id IS NULL;
SELECT 'purchase_tx_amount_or_direction_mismatch_count', COUNT(*)
FROM game_purchases p
JOIN wallet_txs t ON t.id=p.wallet_tx_id
WHERE t.amount<>p.total_price OR t.direction<>'DEBIT' OR t.reason<>'BUY_CARDS';
SELECT 'active_game_headers', 'id status level topic layout rule price sold pool';
SELECT id, status, COALESCE(game_level,'-'),
       COALESCE(tg_topic_id,0), card_layout_version,
       game_rule, card_price, sold_amount, prize_pool
FROM games
WHERE status IN ('LOBBY','RUNNING')
ORDER BY id DESC LIMIT 30;
SQL

echo "===== AVAILABLE DISK ====="
df -h /
echo "===== END OF READ-ONLY REPORT ====="
echo "No database row, production code, or environment setting was changed."
