#!/usr/bin/env bash
# Davarna v1 RC fast read-only NODE2 preflight. No deploy, restart, DB writes,
# Telegram sends, wallet operations, migrations, or secrets shown.
set -Eeuo pipefail
umask 077
cd /opt/davarna-v2

BRANCH="release/v1.0.0-rc1-20261109"
REF="$DAVARNA_V1_RC_REF"
# Pinned release base to avoid relying on a potentially absent local branch.
BASE="22ddf0f60e5eb0e56462503597679d0541efe229"

[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || { echo "BLOCKER: pin DAVARNA_V1_RC_REF"; exit 2; }
[[ "$(git rev-parse "origin/$BRANCH")" == "$REF" ]] || {
  echo "BLOCKER: RC HEAD differs from pinned reference"; exit 2;
}
git merge-base --is-ancestor "$BASE" "$REF" || {
  echo "BLOCKER: release candidate not based on expected release branch"; exit 2;
}

echo "===== PINNED RELEASE CANDIDATE ====="
echo "RC:   $REF"
echo "Base: $(git rev-parse "$BASE")"

echo "===== CHANGED FILES (paths only) ====="
git diff --name-only "$BASE" "$REF"

echo "===== NO CRYPTO / FINANCIAL / MIGRATION DELTA ====="
if git diff --name-only "$BASE" "$REF" |
  grep -E '^(backend/alembic/|backend/app/(models/|services/(crypto|wallet|game_service|payment|deposit|withdraw)|routers/(wallet|crypto|payments))/|davarna-bot/bot/(routers/crypto|keyboards/crypto))'; then
  echo "BLOCKER: high-risk file change in RC"
  exit 2
fi
echo "PASS: no changed high-risk paths found"

echo "===== PRODUCTION CONTAINER HEALTH (OBSERVE ONLY) ====="
for service in davarna-mysql davarna-redis davarna-backend davarna-bot; do
  status="$(docker inspect --format '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$service" 2>/dev/null || true)"
  if [[ -z "$status" ]]; then status="MISSING"; fi
  printf '%s: %s\n' "$service" "$status"
  [[ "$status" == "running/healthy" ]] || {
    echo "BLOCKER: $service not reported running/healthy"; exit 2;
  }
done

echo "===== BACKEND HEALTH ====="
curl -fsS --max-time 10 -o /dev/null http://127.0.0.1:18080/health/db || {
  echo "BLOCKER: backend database-health endpoint unavailable"; exit 2;
}
echo "PASS: backend health HTTP"

echo "===== BOT PERSISTENT STORAGE MOUNT ====="
store="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/storage"}}{{.Source}}{{end}}{{end}}' davarna-bot)"
[[ -n "$store" && -d "$store" ]] || {
  echo "BLOCKER: bot persistent storage not available"; exit 2;
}
echo "PASS: bot storage is bind-mounted; path is not printed"
echo "NOTE: requires backup before production release"

echo "===== HOST RESOURCES ====="
df -h /opt/davarna
free -h | head -n 3
echo "===== CURRENT DEPLOYMENT REFERENCES ====="
for service in davarna-backend davarna-bot; do
  image="$(docker inspect --format '{{.Image}}' "$service")"
  echo "$service current-image-sha=$image"
done
if [[ -d /opt/davarna/.git ]]; then
  echo "production-git-sha=$(git -C /opt/davarna rev-parse HEAD)"
fi
echo "===== RC PRE-FLIGHT CHECKS PASSED (READ-ONLY) ====="
echo "NOT INCLUDED: backup verification, active game/transaction check,"
echo "real Telegram staging delivery, authorization, merge or deployment."
