#!/usr/bin/env bash
# Verified backup of current Davarna Production; no restart/build/migration.
set -Eeuo pipefail
umask 077
cd /opt/davarna-v2

PROD=/opt/davarna
ROOT=/root/davarna-v2-release-backups
BACKEND=davarna-backend:v2-937ef711a9db
BOT=davarna-bot:v2-937ef711a9db
BRANCH=feature/ui-ux-refresh-tambola-v2-20261106

die() { echo "BLOCKER: $*" >&2; exit 2; }
[[ "$(id -u)" == 0 ]] || die "root is required"
[[ "$(git branch --show-current)" == "$BRANCH" ]] || die "Wrong checkout branch"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || die "Tracked files were modified"
[[ -f "$PROD/.env.prod" && -f "$PROD/davarna-bot/.env.prod" ]] || die "Missing original environment files"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Running}}' "$c")" == true ]] || die "$c not running"
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || die "$c not healthy"
  [[ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$c")" == davarna ]] ||
    die "Unexpected Compose project for $c"
done
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$BACKEND" ]] || die "Backend image changed"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == "$BOT" ]] || die "Bot image changed"
BACKEND_ID="$(docker inspect -f '{{.Image}}' davarna-backend)"
BOT_ID="$(docker inspect -f '{{.Image}}' davarna-bot)"
[[ "$(docker image inspect -f '{{.Id}}' "$BACKEND")" == "$BACKEND_ID" ]] || die "Backend image tag moved"
[[ "$(docker image inspect -f '{{.Id}}' "$BOT")" == "$BOT_ID" ]] || die "Bot image tag moved"

for c in davarna-backend davarna-bot; do
  [[ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$c")" == "$PROD" ]] ||
    die "Unexpected production Compose working directory for $c"
done

# Verify both storage mount destinations against known production paths.
for spec in "davarna-backend|$PROD/storage" "davarna-bot|$PROD/davarna-bot/storage"; do
  c="${spec%%|*}"
  expected="${spec#*|}"
  [[ -d "$expected" ]] || die "Missing storage: $expected"
  found="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/storage"}}{{.Source}}{{end}}{{end}}' "$c")"
  [[ -n "$found" && "$(readlink -f "$found")" == "$(readlink -f "$expected")" ]] ||
    die "Storage mount mismatch for $c"
done
[[ "$(curl -sS --connect-timeout 3 --max-time 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/health/db || true)" == 200 ]] ||
  die "Backend health probe failed"

declare -A seen=()
compose=()
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  csv="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$c")"
  [[ -n "$csv" && "$csv" != "<no value>" ]] || die "Missing Compose labels for $c"
  IFS=',' read -r -a paths <<< "$csv"
  for p in "${paths[@]}"; do
    [[ "$p" == /* && -f "$p" ]] || die "Missing Compose file: $p"
    if [[ -z "${seen[$p]+set}" ]]; then
      seen["$p"]=1
      compose+=("$p")
    fi
  done
done

free_kb="$(df -Pk "$PROD" | awk 'NR==2 {print $4}')"
storage_kb="$(du -sk "$PROD/storage" "$PROD/davarna-bot/storage" | awk '{s+=$1} END{print s+0}')"
[[ "$free_kb" =~ ^[0-9]+$ && "$storage_kb" =~ ^[0-9]+$ ]] || die "Disk stats unavailable"
(( free_kb > storage_kb * 2 + 6 * 1024 * 1024 )) || die "Insufficient backup disk headroom"
printf 'Preflight OK: storage=%s MiB, free=%s MiB, compose files=%s\n' \
  "$((storage_kb / 1024))" "$((free_kb / 1024))" "${#compose[@]}"

mkdir -p -m 0700 "$ROOT"
chmod 0700 "$ROOT"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
DIR="$(mktemp -d "$ROOT/release-$stamp.XXXXXX")"
chmod 0700 "$DIR"
complete=0
cleanup() {
  if (( complete != 1 )); then
    echo "INCOMPLETE BACKUP — removing unverified temporary archive" >&2
    [[ "$DIR" == "$ROOT"/release-* && -d "$DIR" ]] && rm -rf -- "$DIR"
  fi
}
trap cleanup EXIT
mkdir -m 0700 "$DIR/configs" "$DIR/data" "$DIR/images"

{
  printf 'UTC=%s\nbranch=%s\ncommit=%s\n' "$stamp" "$BRANCH" "$(git rev-parse HEAD)"
  printf 'backend=%s\nbackend_image_id=%s\n' "$BACKEND" "$BACKEND_ID"
  printf 'bot=%s\nbot_image_id=%s\n' "$BOT" "$BOT_ID"
  echo "production_workdir=$PROD"
} > "$DIR/manifest.txt"

echo "===== CONFIG SNAPSHOT (ROOT ONLY) ====="
i=0
for p in "${compose[@]}"; do
  i=$((i+1))
  cp -L "$p" "$DIR/configs/compose-$i.yml"
  chmod 0600 "$DIR/configs/compose-$i.yml"
  printf 'compose_%s=%s\n' "$i" "$p" >> "$DIR/manifest.txt"
done
for pair in \
  "$PROD/.env.prod|root.env.prod" \
  "$PROD/.env|root.env" \
  "$PROD/backend/.env|backend.env" \
  "$PROD/davarna-bot/.env.prod|bot.env.prod" \
  "$PROD/davarna-bot/.env|bot.env"; do
  p="${pair%%|*}"
  dest="${pair#*|}"
  if [[ -f "$p" ]]; then
    cp -L "$p" "$DIR/configs/$dest"
    chmod 0600 "$DIR/configs/$dest"
    printf 'env_file=%s\n' "$p" >> "$DIR/manifest.txt"
  fi
done

echo "===== MYSQL LOGICAL BACKUP ====="
# Password read inside container; never appears in host shell arguments/output.
docker exec davarna-mysql sh -ec '
  : "${MYSQL_ROOT_PASSWORD:?missing MySQL root password}"
  : "${MYSQL_DATABASE:?missing database name}"
  export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"
  exec mysqldump -uroot --single-transaction --skip-lock-tables --quick \
    --routines --events --triggers --hex-blob --no-tablespaces \
    --set-gtid-purged=OFF --default-character-set=utf8mb4 "$MYSQL_DATABASE"
' | nice -n 10 gzip -1 > "$DIR/data/mysql.sql.gz"
gzip -t "$DIR/data/mysql.sql.gz"
python3 - "$DIR/data/mysql.sql.gz" <<'PY'
import gzip, sys
from pathlib import Path
p = Path(sys.argv[1])
if p.stat().st_size < 2048:
    raise SystemExit("MySQL dump unexpectedly small")
with gzip.open(p, "rt", encoding="utf-8", errors="replace") as f:
    if "MySQL dump" not in f.read(1024):
        raise SystemExit("Unrecognized MySQL dump header")
print("SQL backup verified (header + gzip)")
PY

echo "===== RECEIPTS AND BOT STORAGE ====="
tar -C "$PROD" -cf - storage davarna-bot/storage |
  nice -n 10 gzip -1 > "$DIR/data/storage.tar.gz"
gzip -t "$DIR/data/storage.tar.gz"
tar -tzf "$DIR/data/storage.tar.gz" >/dev/null

echo "===== BACKEND/BOT IMAGE ARCHIVE ====="
docker image save "$BACKEND" "$BOT" |
  nice -n 10 gzip -1 > "$DIR/images/backend-bot.tar.gz"
gzip -t "$DIR/images/backend-bot.tar.gz"
tar -tzf "$DIR/images/backend-bot.tar.gz" >/dev/null

echo "===== SHA256 VALIDATION ====="
(
  cd "$DIR"
  sha256sum manifest.txt configs/* data/*.gz images/*.gz > SHA256SUMS
  sha256sum -c SHA256SUMS
)
complete=1
trap - EXIT
echo "===== BACKUP VERIFIED ====="
printf 'Backup directory (root-only): %s\n' "$DIR"
du -h "$DIR/data/"* "$DIR/images/"*
echo "Do NOT restore production DB as part of an ordinary UI-only rollback."
