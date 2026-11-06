#!/usr/bin/env bash
# Read-only release inventory for Davarna NODE2. Does not run Compose or read secrets.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "===== RELEASE INVENTORY: READ ONLY ====="
BRANCH="$(git branch --show-current)"
HEAD="$(git rev-parse HEAD)"
BASE="937ef711a9db45d85099e066733ceede72848cf1"
printf 'Checkout: %s\nBranch: %s\nHead: %s\nBaseline: %s\n' "$ROOT" "$BRANCH" "$HEAD" "$BASE"

if [[ "$BRANCH" != "feature/ui-ux-refresh-tambola-v2-20261106" ]]; then
  echo "BLOCKER: unexpected branch; no production work."
  exit 2
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "BLOCKER: tracked working tree is dirty; no production work."
  exit 2
fi
git merge-base --is-ancestor "$BASE" "$HEAD" || {
  echo "BLOCKER: release does not descend from verified baseline."
  exit 2
}

echo "===== SOURCE SCOPE ====="
git diff --name-only "$BASE" "$HEAD" | sed -n '1,90p'
if git diff --name-only "$BASE" "$HEAD" |
  grep -Eq '(^backend/alembic/|(^|/)(Dockerfile|docker-compose[^/]*|compose\.ya?ml)$|^backend/app/models/|^backend/app/services/(finance|game)_service\.py)'; then
  echo "BLOCKER: sensitive schema, deployment, or game/finance engine change detected."
  exit 2
fi
echo "Source gate: no schema/deployment/game-engine changes since baseline."

echo "===== ACTIVE CONTAINERS ====="
for container in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  if ! docker inspect "$container" >/dev/null 2>&1; then
    echo "BLOCKER: container $container is missing."
    exit 2
  fi
  echo "--- $container ---"
  docker inspect --format 'running={{.State.Running}} status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} image_id={{.Image}}' "$container"
  docker inspect --format 'compose_project={{index .Config.Labels "com.docker.compose.project"}} compose_service={{index .Config.Labels "com.docker.compose.service"}}' "$container"
  docker inspect --format 'compose_workdir={{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$container"
  docker inspect --format 'compose_files={{index .Config.Labels "com.docker.compose.project.config_files"}}' "$container"
  running="$(docker inspect --format '{{.State.Running}}' "$container")"
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container")"
  if [[ "$running" != "true" || "$health" == "unhealthy" ]]; then
    echo "BLOCKER: production container is not healthy/running."
    exit 2
  fi
done

echo "===== CURRENT IMAGE NAMES ====="
docker inspect --format 'backend={{.Config.Image}}' davarna-backend
docker inspect --format 'bot={{.Config.Image}}' davarna-bot

echo "===== BACKUP PREREQUISITES ====="
if docker exec davarna-mysql sh -c 'command -v mysqldump >/dev/null 2>&1'; then
  echo "MySQL dump client: available."
else
  echo "BLOCKER: mysqldump is not available in production database container."
  exit 2
fi
if command -v gzip >/dev/null 2>&1 && command -v sha256sum >/dev/null 2>&1; then
  echo "Host gzip/sha256sum: available."
else
  echo "BLOCKER: gzip or sha256sum missing on host."
  exit 2
fi
df -h "$ROOT"
free -m

echo "===== BACKEND LOCAL HEALTH ====="
HTTP_CODE="$(curl -sS --connect-timeout 3 --max-time 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/health/db || true)"
printf '127.0.0.1:18080/health/db HTTP %s\n' "$HTTP_CODE"
if [[ "$HTTP_CODE" != "200" ]]; then
  echo "BLOCKER: production backend local database health is not HTTP 200."
  exit 2
fi

echo "===== INVENTORY PASSED ====="
echo "No service was restarted, replaced, deployed, or backed up."
