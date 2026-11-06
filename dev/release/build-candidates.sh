#!/usr/bin/env bash
# Prepare candidate images by layering ONLY reviewed UX code on verified live base images.
# Never runs compose, changes live containers, migrates or writes to MySQL.
set -Eeuo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
die() { echo "BLOCKER: $*" >&2; exit 2; }

[[ "$(id -u)" == 0 ]] || die "Run as root for protected release records"
BRANCH="feature/ui-ux-refresh-tambola-v2-20261106"
BASE_SHA="937ef711a9db45d85099e066733ceede72848cf1"
BACKEND_BASE="davarna-backend:v2-937ef711a9db"
BOT_BASE="davarna-bot:v2-937ef711a9db"
BACKEND_ROLLBACK="davarna-backend:rollback-20261106-937ef711"
BOT_ROLLBACK="davarna-bot:rollback-20261106-937ef711"

[[ "$(git branch --show-current)" == "$BRANCH" ]] || die "Wrong branch"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || die "Dirty tracked worktree"
git merge-base --is-ancestor "$BASE_SHA" HEAD || die "Baseline is not an ancestor"

declare -A allowed=()
for file in \
  backend/app/routers/bot_router.py \
  backend/app/routers/mini_router.py \
  backend/app/schemas/mini.py \
  backend/app/static/mini/app.js \
  backend/app/static/mini/index.html \
  backend/app/static/mini/ux-v2.css \
  davarna-bot/bot/keyboards/admin_games.py \
  davarna-bot/bot/routers/admin_finance.py \
  davarna-bot/bot/routers/admin_games.py \
  davarna-bot/bot/routers/help.py \
  davarna-bot/bot/routers/wallet.py \
  davarna-bot/bot/services/admin_topics.py \
  davarna-bot/bot/workers/notifier.py; do
  allowed["$file"]=1
done

while IFS= read -r file; do
  case "$file" in
    backend/app/*|davarna-bot/bot/*|backend/alembic/*|backend/Dockerfile|davarna-bot/Dockerfile|docker-compose*)
      [[ -n "${allowed[$file]+set}" ]] ||
        die "Unreviewed application/deployment change: $file"
      ;;
  esac
done < <(git diff --name-only "$BASE_SHA" HEAD)

[[ -n "${DAVARNA_RELEASE_BACKUP:-}" ]] || die "Set DAVARNA_RELEASE_BACKUP to verified backup directory"
BACKUP="$(readlink -f "$DAVARNA_RELEASE_BACKUP")"
case "$BACKUP" in
  /root/davarna-v2-release-backups/release-*) ;;
  *) die "Backup path outside protected release directory" ;;
esac
[[ -d "$BACKUP" && -f "$BACKUP/SHA256SUMS" && -f "$BACKUP/manifest.txt" ]] ||
  die "Verified backup manifest not found"
grep -Fxq "backend=$BACKEND_BASE" "$BACKUP/manifest.txt" || die "Backend backup base mismatch"
grep -Fxq "bot=$BOT_BASE" "$BACKUP/manifest.txt" || die "Bot backup base mismatch"
(
  cd "$BACKUP"
  sha256sum --quiet --check SHA256SUMS
) || die "Backup checksum verification failed"

for pair in "davarna-backend|$BACKEND_BASE" "davarna-bot|$BOT_BASE"; do
  ct="${pair%%|*}"
  tag="${pair#*|}"
  [[ "$(docker inspect -f '{{.State.Running}}' "$ct")" == true ]] || die "$ct is not running"
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$ct")" == healthy ]] || die "$ct not healthy"
  [[ "$(docker inspect -f '{{.Config.Image}}' "$ct")" == "$tag" ]] || die "$ct image changed since backup"
  live_id="$(docker inspect -f '{{.Image}}' "$ct")"
  [[ "$(docker image inspect -f '{{.Id}}' "$tag")" == "$live_id" ]] || die "Tag was moved: $tag"
done

available_kib="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
disk_kib="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
[[ "$available_kib" =~ ^[0-9]+$ && "$disk_kib" =~ ^[0-9]+$ ]] ||
  die "Cannot determine resource headroom"
(( available_kib >= 1280 * 1024 )) || die "Available RAM under 1280 MiB; do not build on this host"
(( disk_kib >= 6 * 1024 * 1024 )) || die "Free disk space under 6 GiB"
[[ "$(curl -sS --connect-timeout 3 --max-time 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/health/db || true)" == "200" ]] ||
  die "Backend local health probe failed"

REV="$(git rev-parse --short=12 HEAD)"
BACKEND_NEW="davarna-backend:ux5-$REV"
BOT_NEW="davarna-bot:ux5-$REV"
for tag in "$BACKEND_NEW" "$BOT_NEW"; do
  if docker image inspect "$tag" >/dev/null 2>&1; then
    die "Candidate tag already exists: $tag. Inspect it before retrying to avoid overwriting."
  fi
done

echo "===== PIN EXISTING IMAGES FOR ROLLBACK ====="
for pair in "$BACKEND_BASE|$BACKEND_ROLLBACK" "$BOT_BASE|$BOT_ROLLBACK"; do
  src="${pair%%|*}"
  dst="${pair#*|}"
  if docker image inspect "$dst" >/dev/null 2>&1; then
    [[ "$(docker image inspect -f '{{.Id}}' "$dst")" == "$(docker image inspect -f '{{.Id}}' "$src")" ]] ||
      die "Rollback tag already exists but points to a different image: $dst"
  else
    docker image tag "$src" "$dst"
  fi
  printf 'ROLLBACK TAG: %s\n' "$dst"
done

TEMP="$(mktemp -d /tmp/davarna-ux-build.XXXXXX)"
cleanup() {
  case "$TEMP" in
    /tmp/davarna-ux-build.*) [[ ! -d "$TEMP" ]] || rm -rf -- "$TEMP" ;;
  esac
}
trap cleanup EXIT
mkdir -p "$TEMP/backend" "$TEMP/bot"

echo "===== STAGE ONLY ALLOWLISTED GIT FILES ====="
backend_paths=(
  backend/app/routers/bot_router.py
  backend/app/routers/mini_router.py
  backend/app/schemas/mini.py
  backend/app/static/mini/app.js
  backend/app/static/mini/index.html
  backend/app/static/mini/ux-v2.css
)
bot_paths=(
  davarna-bot/bot/keyboards/admin_games.py
  davarna-bot/bot/routers/admin_finance.py
  davarna-bot/bot/routers/admin_games.py
  davarna-bot/bot/routers/help.py
  davarna-bot/bot/routers/wallet.py
  davarna-bot/bot/services/admin_topics.py
  davarna-bot/bot/workers/notifier.py
)
git archive HEAD -- "${backend_paths[@]}" | tar -x -C "$TEMP/backend"
git archive HEAD -- "${bot_paths[@]}" | tar -x -C "$TEMP/bot"
cp dev/release/Dockerfile.backend-ux "$TEMP/backend/Dockerfile"
cp dev/release/Dockerfile.bot-ux "$TEMP/bot/Dockerfile"

echo "===== BUILD BACKEND CANDIDATE (NO NETWORK) ====="
docker build --network=none --pull=false \
  --build-arg "BASE_IMAGE=$BACKEND_BASE" \
  --tag "$BACKEND_NEW" "$TEMP/backend"

echo "===== QUICK BACKEND SYNTAX CHECK (NO NETWORK) ====="
docker run --rm --network none --memory 256m --entrypoint python "$BACKEND_NEW" \
  -m compileall -q \
  /app/app/routers/bot_router.py \
  /app/app/routers/mini_router.py \
  /app/app/schemas/mini.py

available_kib="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
(( available_kib >= 1024 * 1024 )) ||
  die "Available RAM below 1024 MiB after backend candidate; stop before bot build"

echo "===== BUILD BOT CANDIDATE (NO NETWORK) ====="
docker build --network=none --pull=false \
  --build-arg "BASE_IMAGE=$BOT_BASE" \
  --tag "$BOT_NEW" "$TEMP/bot"

echo "===== QUICK BOT SYNTAX CHECK (NO NETWORK) ====="
docker run --rm --network none --memory 256m --entrypoint python "$BOT_NEW" \
  -m compileall -q \
  /app/bot/keyboards/admin_games.py \
  /app/bot/routers/admin_finance.py \
  /app/bot/routers/admin_games.py \
  /app/bot/routers/help.py \
  /app/bot/routers/wallet.py \
  /app/bot/services/admin_topics.py \
  /app/bot/workers/notifier.py

RECORD="/root/davarna-v2-release-backups/candidate-ux5-$REV.txt"
{
  printf 'source_commit=%s\n' "$(git rev-parse HEAD)"
  printf 'verified_backup=%s\n' "$BACKUP"
  printf 'backend_candidate=%s\n' "$BACKEND_NEW"
  printf 'backend_candidate_id=%s\n' "$(docker image inspect -f '{{.Id}}' "$BACKEND_NEW")"
  printf 'bot_candidate=%s\n' "$BOT_NEW"
  printf 'bot_candidate_id=%s\n' "$(docker image inspect -f '{{.Id}}' "$BOT_NEW")"
  printf 'backend_rollback=%s\n' "$BACKEND_ROLLBACK"
  printf 'bot_rollback=%s\n' "$BOT_ROLLBACK"
} > "$RECORD"
chmod 0600 "$RECORD"
echo "===== CANDIDATE IMAGES VERIFIED ====="
printf 'Backend: %s\nBot: %s\nRollback Backend: %s\nRollback Bot: %s\n' \
  "$BACKEND_NEW" "$BOT_NEW" "$BACKEND_ROLLBACK" "$BOT_ROLLBACK"
echo "No Production container has been recreated or restarted."
