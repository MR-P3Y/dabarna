#!/usr/bin/env bash
# V1.0 candidate readiness inspection. STRICTLY READ-ONLY.
# No checkout, rebuild, docker compose, restart, git merge, SQL write, or Telegram send.
set -Eeuo pipefail
umask 077

cd /opt/davarna-v2
BRANCH="release/v1.0-readiness-20261109"
BASE="release/combined-forum-mini-candidate-20261107"
REF="${DAVARNA_V1_REF:?Set a pinned 40-character candidate commit SHA}"
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || { echo "BLOCKER: invalid SHA"; exit 2; }
test "$(git rev-parse "origin/$BRANCH")" = "$REF" || {
  echo "BLOCKER: candidate branch moved"; exit 2;
}
git merge-base --is-ancestor "origin/$BASE" "$REF" || {
  echo "BLOCKER: candidate not based on release branch"; exit 2;
}

echo "===== V1.0 CANDIDATE / SCOPE ====="
printf 'candidate=%s\n' "$REF"
echo "Change-set against release branch:"
git diff --name-only "origin/$BASE" "$REF"
echo "Verify only forum, delivery, tests and release docs changed"
while IFS= read -r path; do
  case "$path" in
    backend/app/routers/mini_router.py|\
    backend/tests/test_game_forum_lifecycle_contract.py|\
    davarna-bot/bot/config.py|\
    davarna-bot/bot/services/lifecycle_delivery.py|\
    davarna-bot/bot/services/notify_store.py|\
    davarna-bot/bot/services/user_forum_navigation.py|\
    davarna-bot/bot/services/user_topics.py|\
    davarna-bot/bot/workers/notifier.py|\
    davarna-bot/tests/test_lifecycle_delivery_ack.py|\
    dev/audit/game_lifecycle_rules_matrix_20261109.md|\
    dev/release/telegram-33-34-one-pass-release-gate-20261109.md|\
    dev/release/test-telegram-lifecycle-ack-20261109.sh|\
    dev/release/v1-readiness-only-20261109.sh|\
    dev/release/v1-freeze-readme-20261109.md)
      ;;
    *) echo "BLOCKER: unexpected changed path: $path"; exit 3 ;;
  esac
done < <(git diff --name-only "origin/$BASE" "$REF")

echo "===== PRODUCTION CONTAINERS (STATUS ONLY) ====="
for name in davarna-backend davarna-bot davarna-redis davarna-mysql; do
  status="$(docker inspect \
    --format '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' \
    "$name")" || { echo "BLOCKER: missing container $name"; exit 4; }
  printf '%s: %s\n' "$name" "$status"
  [[ "$status" == running/healthy || "$status" == running/no-healthcheck ]] || {
    echo "BLOCKER: container is not healthy: $name"; exit 4;
  }
done

echo "===== LOCAL BACKEND HEALTH (NO AUTH DATA) ====="
curl -fsS --max-time 7 -o /dev/null "http://127.0.0.1:18080/health/db" || {
  echo "BLOCKER: backend /health/db failed"; exit 5;
}
echo "PASS: backend /health/db"
curl -fsS --max-time 7 -o /dev/null "http://127.0.0.1:18080/mini/index.html" || {
  echo "BLOCKER: mini/index.html failed"; exit 5;
}
echo "PASS: mini/index.html"

echo "===== SELECTED BACKEND FLAGS (NO SECRETS) ====="
docker exec davarna-backend sh -lc '
for key in GAME_TAMBOLA_V2_ENABLED GAME_AUTO_DRAW_ENABLED GAME_AUTOPILOT_RUNTIME_ENABLED; do
  value=$(printenv "$key" 2>/dev/null || true)
  if [ -z "$value" ]; then value="<not explicitly set>"; fi
  printf "%s=%s\n" "$key" "$value"
done
'

echo "===== PRODUCTION DB (SELECT-ONLY) ====="
docker exec -i davarna-mysql sh -lc '
set -eu
export MYSQL_PWD="$MYSQL_PASSWORD"
mysql --batch -u"$MYSQL_USER" "$MYSQL_DATABASE" -e "
SELECT version_num AS alembic_version FROM alembic_version;
SELECT id, status, game_level, game_rule, draw_mode, sold_amount, prize_pool
  FROM games WHERE status IN (\"LOBBY\", \"RUNNING\")
  ORDER BY id DESC LIMIT 20;
SELECT level, enabled, scheduler_mode, start_mode, draw_mode,
       game_rule, min_unique_players
  FROM game_autopilot_configs ORDER BY level;
SELECT COUNT(*) AS invalid_v2_game_rule_count
  FROM games
  WHERE card_layout_version = 2 AND game_rule NOT IN (\"LINE\", \"FULL_CARD\");
"'

echo "===== BOT ACK STORAGE (READ-ONLY, NO CONTENT PRINTED) ====="
docker exec davarna-bot python -c '
import json, pathlib
path=pathlib.Path("/app/storage/notif_state.json")
if not path.exists():
    print("ACK_STORE=missing (inspect before rollout)")
else:
    try:
        data=json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("events", {}), dict):
            raise ValueError("invalid state structure")
        print("ACK_STORE=valid_json")
    except Exception:
        print("ACK_STORE=CORRUPT")
        raise SystemExit(1)
'

echo "===== HOST DISK / ERROR COUNTS ====="
df -h /opt/davarna-v2 | tail -n 1
for name in davarna-backend davarna-bot; do
  count="$(docker logs --since 10m --tail 500 "$name" 2>&1 |
    grep -Eic '(ERROR|Traceback|Exception)' || true)"
  printf '%s recent_error_lines=%s\n' "$name" "$count"
done

echo "===== V1.0 READ-ONLY PRECHECK COMPLETE ====="
echo "NOT DEPLOYED. NO MERGE. NO DB WRITE. NO TELEGRAM SEND."
