#!/usr/bin/env bash
# Build pinned V2 images and preserve current Docker images for rollback.
# NO production services, MySQL rows, env files, or bot sessions are changed.
set -Eeuo pipefail

ROOT=/opt/davarna
SRC=/opt/davarna-v2
BACKUP=/root/davarna-v2-release-backups/davarna-pre-v2-20261105_223632.sql.gz
RELEASE_DIR=/root/davarna-v2-release-backups
BRANCH=fix/tambola-finance-idempotency-20261105

if [[ "$(id -u)" != 0 ]]; then
  echo "FAIL: run as root on NODE2" >&2
  exit 1
fi
# A linked Git worktree has a .git FILE, not a .git directory.
# Ask Git to validate the checkout rather than assuming its on-disk layout.
if [[ ! -r "$ROOT/.env.prod" ]]; then
  echo "FAIL: production environment is missing or unreadable" >&2
  exit 1
fi
if [[ ! -d "$SRC" ]] || ! git -C "$SRC" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "FAIL: development source is not a valid Git working tree" >&2
  exit 1
fi
if [[ "$(git -C "$SRC" rev-parse --show-toplevel)" != "$SRC" ]]; then
  echo "FAIL: development checkout root is unexpected" >&2
  exit 1
fi
if [[ ! -f "$BACKUP" ]]; then
  echo "FAIL: verified backup not found at $BACKUP" >&2
  exit 1
fi
gzip -t "$BACKUP"
echo "Backup compression checked: $(basename "$BACKUP")"
cd "$SRC"
if [[ "$(git branch --show-current)" != "$BRANCH" ]]; then
  echo "FAIL: unexpected development Git branch" >&2
  exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "FAIL: tracked development files have local modifications" >&2
  exit 1
fi
git pull --ff-only origin "$BRANCH"

SHA="$(git rev-parse --short=12 HEAD)"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKEND_NEW="davarna-backend:v2-$SHA"
BOT_NEW="davarna-bot:v2-$SHA"
BACKEND_OLD="davarna-backend:before-v2-$STAMP"
BOT_OLD="davarna-bot:before-v2-$STAMP"
install -d -m 700 "$RELEASE_DIR"

echo "===== CAPTURE CURRENT RUNNING IMAGE IDS ====="
OLD_BACKEND_ID="$(docker inspect --format '{{.Image}}' davarna-backend)"
OLD_BOT_ID="$(docker inspect --format '{{.Image}}' davarna-bot)"
docker image inspect "$OLD_BACKEND_ID" "$OLD_BOT_ID" >/dev/null
docker image tag "$OLD_BACKEND_ID" "$BACKEND_OLD"
docker image tag "$OLD_BOT_ID" "$BOT_OLD"

echo "===== BUILD NEW IMMUTABLE-TAG CANDIDATES ====="
docker build --label "org.opencontainers.image.revision=$SHA" -t "$BACKEND_NEW" "$SRC/backend"
docker build --label "org.opencontainers.image.revision=$SHA" -t "$BOT_NEW" "$SRC/davarna-bot"

echo "===== VERIFY IMAGE PYTHON SOURCE COMPILATION (OFFLINE) ====="
docker run --rm --network none --entrypoint python \
  "$BACKEND_NEW" -m compileall -q app
docker run --rm --network none --entrypoint python \
  "$BOT_NEW" -m compileall -q bot

echo "===== VERIFY PRODUCTION COMPOSE WITH SAFE V2-OFF OVERLAY ====="
export TAMBOLA_V2_BACKEND_IMAGE="$BACKEND_NEW"
export TAMBOLA_V2_BOT_IMAGE="$BOT_NEW"
(
  cd "$ROOT"
  docker compose --env-file .env.prod \
    -f docker-compose.yml \
    -f "$SRC/deploy/tambola-v2-inactive.compose.yml" \
    config --quiet
)

STAGED="$RELEASE_DIR/v2-staged-$STAMP.env"
{
  printf 'TAMBOLA_V2_BACKEND_IMAGE=%s\n' "$BACKEND_NEW"
  printf 'TAMBOLA_V2_BOT_IMAGE=%s\n' "$BOT_NEW"
  printf 'TAMBOLA_OLD_BACKEND_IMAGE=%s\n' "$BACKEND_OLD"
  printf 'TAMBOLA_OLD_BOT_IMAGE=%s\n' "$BOT_OLD"
  printf 'TAMBOLA_RELEASE_GIT_SHA=%s\n' "$SHA"
  printf 'TAMBOLA_BACKUP_FILE=%s\n' "$BACKUP"
} > "$STAGED"
chmod 600 "$STAGED"

echo "===== CANDIDATE READY — PRODUCTION UNCHANGED ====="
echo "Release: $SHA"
echo "New backend image: $BACKEND_NEW"
echo "New bot image: $BOT_NEW"
echo "Rollback backend image: $BACKEND_OLD"
echo "Rollback bot image: $BOT_OLD"
echo "Saved release manifest: $STAGED"
echo "Do not run docker compose up yet; first review the staged candidate."
