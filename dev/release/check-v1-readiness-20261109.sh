#!/usr/bin/env bash
# Davarna v1.0 readiness: read-only source and operational checks.
# NEVER deploys, restarts, writes SQL, or sends Telegram messages.
set -Eeuo pipefail
cd /opt/davarna-v2
umask 077
BRANCH="fix/telegram-lifecycle-delivery-ack-20261109"
REF="$DAVARNA_V1_CANDIDATE_REF"
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || { echo "BLOCKER: pinned candidate SHA required"; exit 2; }
[[ "$(git rev-parse "origin/$BRANCH")" == "$REF" ]] || {
  echo "BLOCKER: remote candidate SHA mismatch"; exit 2;
}
BASE="origin/release/combined-forum-mini-candidate-20261107"
git rev-parse --verify "$BASE" >/dev/null

blockers=0
block() { echo "BLOCKER: $*"; blockers=$((blockers + 1)); }

echo "===== PINNED SOURCE / CHANGE SCOPE ====="
echo "candidate=$REF"
echo "server_worktree=$(git rev-parse HEAD)"
echo "server_branch=$(git branch --show-current)"
echo "source_base=$(git rev-parse "$BASE")"
if ! git merge-base --is-ancestor "$BASE" "$REF"; then
  block "Candidate does not descend from current release base"
fi
while IFS= read -r path; do
  [[ -z "$path" ]] && continue
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
    dev/release/check-v1-readiness-20261109.sh)
      echo "IN_SCOPE: $path" ;;
    *) block "Unexpected candidate path: $path" ;;
  esac
done < <(git diff --name-only "$BASE" "$REF")

echo "===== PRODUCTION CONTAINER STATUS (READ ONLY) ====="
for svc in davarna-mysql davarna-redis davarna-backend davarna-bot; do
  status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$svc" 2>/dev/null || true)"
  [[ -n "$status" ]] || status="missing"
  image_id="$(docker inspect --format '{{.Image}}' "$svc" 2>/dev/null || true)"
  echo "$svc status=$status image=$image_id"
  [[ "$status" == "healthy" || "$status" == "running" ]] || block "$svc unhealthy or missing"
done

echo "===== DB REVISION AND ACTIVE GAME COUNT (SELECT ONLY) ====="
db_rev="$(docker exec davarna-mysql sh -lc \
  'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u"$MYSQL_USER" "$MYSQL_DATABASE" --batch --skip-column-names --silent -e "SELECT version_num FROM alembic_version LIMIT 1;"' \
  2>/dev/null || true)"
if [[ -n "$db_rev" ]]; then
  echo "current_db_revision=$db_rev"
else
  block "DB revision unavailable"
fi
active_count="$(docker exec davarna-mysql sh -lc \
  'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u"$MYSQL_USER" "$MYSQL_DATABASE" --batch --skip-column-names --silent -e "SELECT COUNT(*) FROM games WHERE status IN (0x4c4f424259,0x52554e4e494e47);"' \
  2>/dev/null || true)"
if [[ "$active_count" =~ ^[0-9]+$ ]]; then
  echo "active_lobby_or_running_games=$active_count"
  if (( active_count > 0 )); then
    block "Active LOBBY/RUNNING games; do not release mid-game"
  fi
else
  block "Cannot determine active game count"
fi

echo "===== SAFE RUNTIME FLAGS (NO SECRETS) ====="
docker exec davarna-backend python3 -c \
  'import os; keys=("GAME_TAMBOLA_V2_ENABLED","GAME_AUTOPILOT_RUNTIME_ENABLED","GAME_AUTO_DRAW_ENABLED"); [print(k+"="+os.environ.get(k,"UNSET (source default applies)")) for k in keys]' \
  2>/dev/null || block "Cannot read non-secret runtime flags"

echo "===== LAST 15 MINUTES FATAL / TRACEBACK COUNTS ====="
for svc in davarna-backend davarna-bot; do
  severe="$(docker logs --since 15m --tail 250 "$svc" 2>&1 \
    | grep -Eic 'Traceback \(most recent call last\)|CRITICAL|FATAL' || true)"
  echo "$svc severe_log_lines=$severe"
  [[ "$severe" == "0" ]] || block "Review $svc severe logs"
done

echo "===== RESOURCE SNAPSHOT ====="
df -h /opt/davarna-v2 | tail -n 1
free -m | head -n 3

echo "===== DECISION ====="
echo "Prior isolated tests: PR33 6/6 PASS; PR34 21/21 PASS"
echo "Real Telegram E2E: NOT TESTED (staging waived)"
echo "Production writes performed: NONE"
if (( blockers > 0 )); then
  echo "V1_READINESS=BLOCKED ($blockers findings)"
  exit 1
fi
echo "V1_READINESS=PASS_READ_ONLY_PREFLIGHT"
echo "Release still requires independent rollout approval and rollback backup."
