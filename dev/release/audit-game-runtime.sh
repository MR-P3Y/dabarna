#!/usr/bin/env bash
# Read-only production audit for three game rules and automated draw/autopilot.
set -Eeuo pipefail
cd /opt/davarna-v2

if [[ "$(git branch --show-current)" != "feature/ui-ux-refresh-tambola-v2-20261106" ]]; then
  echo "STOP: unexpected Git branch" >&2; exit 2
fi
if [[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" != "davarna-backend:ux5-f3c649e22593" ]]; then
  echo "STOP: production backend image changed; recheck before continuing" >&2; exit 2
fi
if [[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-backend)" != "healthy" ]]; then
  echo "STOP: production backend is not healthy" >&2; exit 2
fi

echo "===== LIVE GAME ENGINE AUDIT (READ ONLY) ====="
docker exec -i davarna-backend python - <<'PY'
from app.core import config as cfg
from app.core.db import engine

def flag(name):
    return "ON" if bool(getattr(cfg, name)) else "OFF"

print("===== EFFECTIVE BACKEND FLAGS =====")
for name in (
    "GAME_TAMBOLA_V2_ENABLED",
    "GAME_AUTO_DRAW_ENABLED",
    "GAME_AUTOPILOT_RUNTIME_ENABLED",
):
    print(f"{name}={flag(name)}")

def show(db, title, sql):
    print(f"\n===== {title} =====")
    rows = db.exec_driver_sql(sql).mappings().all()
    if not rows:
        print("(no rows)")
    for row in rows:
        print(" | ".join(f"{key}={value if value is not None else '-'}" for key, value in row.items()))

# One explicitly read-only transaction. Do not print users, tokens or card numbers.
with engine.connect() as db:
    try:
        db.exec_driver_sql("START TRANSACTION READ ONLY")
        show(db, "DATABASE MIGRATION", """
            SELECT version_num FROM alembic_version
        """)
        show(db, "GAME COUNTS BY RULE/STATUS", """
            SELECT game_rule, card_layout_version, status,
                   COUNT(*) AS games,
                   SUM(CASE WHEN draw_mode = 'AUTO' THEN 1 ELSE 0 END) AS auto_draw_games,
                   SUM(CASE WHEN execution_source = 'SYSTEM' THEN 1 ELSE 0 END) AS system_games
            FROM games
            GROUP BY game_rule, card_layout_version, status
            ORDER BY game_rule, card_layout_version, status
        """)
        show(db, "ACTIVE GAMES (MAX 20)", """
            SELECT g.id AS game_id, g.status, g.game_level, g.game_rule,
                   g.card_layout_version, g.execution_source,
                   g.draw_mode, g.draw_interval_seconds,
                   (SELECT COUNT(DISTINCT p.user_id) FROM game_purchases p WHERE p.game_id=g.id) AS players,
                   (SELECT COALESCE(SUM(p.qty),0) FROM game_purchases p WHERE p.game_id=g.id) AS purchased_cards,
                   (SELECT COUNT(*) FROM game_cards c WHERE c.game_id=g.id) AS cards_in_db,
                   (SELECT COUNT(*) FROM game_called_numbers n WHERE n.game_id=g.id) AS called_numbers,
                   g.created_at
            FROM games g
            WHERE g.status IN ('LOBBY','RUNNING')
            ORDER BY g.id DESC LIMIT 20
        """)
        show(db, "AUTOPILOT SETTINGS BY LEVEL", """
            SELECT level, enabled, game_rule,
                   scheduler_mode, start_mode, draw_mode,
                   card_price, min_unique_players,
                   draw_interval_seconds, repeat_interval_seconds
            FROM game_autopilot_configs
            ORDER BY FIELD(level, 'LOW','MEDIUM','HIGH')
        """)
        show(db, "AUTO DRAW CONTROLS (ACTIVE OR RECENT, MAX 20)", """
            SELECT a.game_id, g.status AS game_status, g.game_rule,
                   g.draw_mode AS game_draw_mode,
                   a.status AS auto_status, a.interval_seconds,
                   a.cursor, a.next_draw_at,
                   (SELECT COUNT(*) FROM game_called_numbers n WHERE n.game_id=a.game_id) AS called_numbers
            FROM game_auto_draws a JOIN games g ON g.id=a.game_id
            WHERE g.status IN ('LOBBY','RUNNING')
               OR a.status IN ('RUNNING','ARMED','PAUSED')
            ORDER BY a.game_id DESC LIMIT 20
        """)
        show(db, "GAME RULE/LAYOUT MISMATCHES", """
            SELECT COUNT(*) AS incompatible_games
            FROM games
            WHERE (game_rule = 'LEGACY' AND card_layout_version <> 1)
               OR (game_rule IN ('LINE','FULL_CARD') AND card_layout_version <> 2)
               OR game_rule NOT IN ('LEGACY','LINE','FULL_CARD')
        """)
    finally:
        db.rollback()
print("\n===== READ-ONLY AUDIT COMPLETED: NO GAME/FINANCE CHANGES =====")
PY
