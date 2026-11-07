#!/usr/bin/env bash
# PR18 + PR19: authorized, pinned-image production release.
# BACKUP -> VERIFY -> BACKEND -> BOT -> VERIFY; automatic CODE-ONLY rollback on failure.
# Does not restore DB, modify wallet/financial settings, alter crypto addresses,
# enable auto-draw/autopilot, publish Telegram messages or upgrade the OS.
set -Eeuo pipefail
umask 077

ROOT=/opt/davarna-v2
PROD=/opt/davarna
SOURCE=e7517922f08685be99a8f55564da1ad22abeddac
OLD_BACKEND=davarna-backend:rbac-pr14-e087c40bd471
OLD_BOT=davarna-bot:pr13-d9434cb10d71
NEW_BACKEND=davarna-backend:forum-mini-e7517922-stage2
NEW_BOT=davarna-bot:forum-mini-e7517922-stage2
NEW_BACKEND_ID=sha256:b6d2709c3f78ce946a90aeb1b2bd6774acfa6b72a88cd604c370842cc3824850
NEW_BOT_ID=sha256:dccabe74e0d5eaad8d2a2f7df8fc5d5b53a84cfe1d6f172475aaed8b93ca04e2
BASE=$PROD/docker-compose.yml
INACTIVE=$ROOT/deploy/tambola-v2-inactive.compose.yml
MANUAL=/root/davarna-v2-release-backups/tambola-v2-manual.compose.yml
UX5=$ROOT/dev/release/ux5-candidate.compose.yml
PR13=/root/davarna-v2-release-backups/pr13-d9434cb10d71-20261106T183004Z/upgrade.yml
PR14=/root/davarna-v2-release-backups/rbac-pr14-e087c40bd471-20261106T193945Z/upgrade.yml
BACKUP=/root/davarna-v2-release-backups/forum-mini-e7517922-$(date -u +%Y%m%dT%H%M%SZ)
TMP=""
STARTED=0
BOT_STARTED=0

fail() { echo "BLOCKER: $*" >&2; exit 2; }
[[ "${DAVARNA_PROD_DEPLOY_APPROVAL:-}" == "APPROVE_PR18_PR19_PRODUCTION" ]] \
  || fail "explicit approval environment flag missing"
[[ "$(id -u)" == 0 ]] || fail "root required"
exec 9>/run/davarna-forum-mini-deploy.lock
flock -n 9 || fail "deployment lock already held"

declare -a BACKEND_FILES=() BOT_FILES=()
compose_for() {
  local service="$1" overlay="$2"
  shift 2
  local -a args=()
  local file
  if [[ "$service" == backend ]]; then
    for file in "${BACKEND_FILES[@]}"; do args+=(-f "$file"); done
  else
    for file in "${BOT_FILES[@]}"; do args+=(-f "$file"); done
  fi
  (cd "$PROD"; docker compose -p davarna --env-file "$PROD/.env.prod" \
    "${args[@]}" -f "$overlay" "$@")
}
finish() {
  local rc=$?
  trap - EXIT
  if (( rc != 0 && STARTED == 1 )); then
    echo "===== RELEASE FAILED: AUTO-ROLLBACK OF CODE IMAGES =====" >&2
    set +e
    if (( BOT_STARTED == 1 )); then
      compose_for bot "$BACKUP/rollback.yml" up -d --no-deps --no-build --force-recreate bot
    fi
    compose_for backend "$BACKUP/rollback.yml" up -d --no-deps --no-build --force-recreate backend
    echo "ROLLBACK ATTEMPTED. VERIFY BOTH SERVICE HEALTH STATES MANUALLY." >&2
    echo "NEVER blindly restore database.sql.gz over live wallet/payment data." >&2
  fi
  if [[ -n "$TMP" && -d "$TMP" ]]; then rm -rf -- "$TMP"; fi
  exit "$rc"
}
trap finish EXIT

cd "$ROOT"
git cat-file -e "$SOURCE^{commit}" || fail "approved source commit unavailable"
git merge-base --is-ancestor "$SOURCE" origin/feature/ui-ux-refresh-tambola-v2-20261106 \
  || fail "approved code not on expected branch"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] \
    || fail "production container unhealthy: $c"
done
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$OLD_BACKEND" ]] \
  || fail "backend base image tag changed"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == "$OLD_BOT" ]] \
  || fail "bot base image tag changed"
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$(docker image inspect -f '{{.Id}}' "$OLD_BACKEND")" ]] \
  || fail "running backend bytes not equal expected base"
[[ "$(docker inspect -f '{{.Image}}' davarna-bot)" == "$(docker image inspect -f '{{.Id}}' "$OLD_BOT")" ]] \
  || fail "running bot bytes not equal expected base"
[[ "$(docker image inspect -f '{{.Id}}' "$NEW_BACKEND")" == "$NEW_BACKEND_ID" ]] \
  || fail "backend candidate image hash changed"
[[ "$(docker image inspect -f '{{.Id}}' "$NEW_BOT")" == "$NEW_BOT_ID" ]] \
  || fail "bot candidate image hash changed"
for f in "$BASE" "$INACTIVE" "$MANUAL" "$PR13" "$PR14" "$PROD/.env.prod" "$PROD/davarna-bot/.env.prod"; do
  [[ -f "$f" ]] || fail "required config or release file missing: $f"
done
printf '%s\n' services: '  backend:' '    image: davarna-backend:pr13-d9434cb10d71' \
  '  bot:' '    image: davarna-bot:pr13-d9434cb10d71' | cmp -s - "$PR13" \
  || fail "PR13 compose overlay changed"
printf '%s\n' services: '  backend:' '    image: davarna-backend:rbac-pr14-e087c40bd471' \
  '  bot:' '    image: davarna-bot:pr13-d9434cb10d71' | cmp -s - "$PR14" \
  || fail "PR14 compose overlay changed"

load_chain() {
  local container="$1" arrayname="$2" csv f
  csv="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$container")" \
    || fail "Compose labels not available"
  [[ -n "$csv" && "$csv" != "<no value>" ]] || fail "Compose files missing"
  local -a files=()
  IFS=',' read -r -a files <<< "$csv"
  (( ${#files[@]} >= 2 )) || fail "Compose chain too short"
  [[ "${files[0]}" == "$BASE" && "${files[1]}" == "$INACTIVE" ]] \
    || fail "Compose base layers differ"
  local found13=0 found14=0 foundmanual=0
  local -A seen=()
  for f in "${files[@]}"; do
    [[ "$f" == /* && -f "$f" ]] || fail "Compose layer unavailable: $f"
    [[ -z "${seen[$f]+set}" ]] || fail "duplicate Compose layer: $f"
    seen[$f]=1
    case "$f" in
      "$BASE"|"$INACTIVE"|"$UX5") ;;
      "$MANUAL") foundmanual=$((foundmanual+1));;
      "$PR13") found13=$((found13+1));;
      "$PR14") found14=$((found14+1));;
      *) fail "unexpected Compose layer: $f";;
    esac
  done
  (( found13==1 )) || fail "PR13 layer missing"
  if [[ "$container" == davarna-backend ]]; then
    (( foundmanual==1 && found14==1 )) || fail "backend manual/PR14 layers missing"
    [[ "${files[$((${#files[@]}-1))]}" == "$PR14" ]] || fail "backend final layer changed"
  else
    (( foundmanual==0 && found14==0 )) || fail "bot unexpectedly uses backend-only layers"
    [[ "${files[$((${#files[@]}-1))]}" == "$PR13" ]] || fail "bot final layer changed"
  fi
  local -n out="$arrayname"
  out=("${files[@]}")
  echo "PASS: $container Compose chain"
}
load_chain davarna-backend BACKEND_FILES
load_chain davarna-bot BOT_FILES
[[ "$(curl -fsS --max-time 8 http://127.0.0.1:18080/health/db)" == '{"ok":true}' ]] \
  || fail "backend database health endpoint failed"
(( $(df -Pk "$PROD" | awk 'NR==2 {print $4}') > 3 * 1024 * 1024 )) \
  || fail "less than 3 GiB disk free"
available=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
(( available > 650 * 1024 )) || fail "less than 650 MiB free RAM"

runtime_snapshot() {
  docker exec -i davarna-backend python - <<'PY'
import hashlib, json
from sqlalchemy import func, select
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.settings import AppSetting
from app.models.wallet import Wallet, WalletTx
from app.models.finance import DepositRequest, WithdrawRequest
from app.models.crypto import CryptoDepositRequest
from app.models.game import Game

flags={
    "t_v2": bool(cfg.GAME_TAMBOLA_V2_ENABLED),
    "auto_draw": bool(cfg.GAME_AUTO_DRAW_ENABLED),
    "autopilot": bool(cfg.GAME_AUTOPILOT_RUNTIME_ENABLED),
}
if flags != {"t_v2": True, "auto_draw": False, "autopilot": False}:
    raise SystemExit("BLOCKER: game engine flags do not match approved scope")
with SessionLocal() as db:
    migration=db.connection().exec_driver_sql(
        "SELECT version_num FROM alembic_version"
    ).scalar_one()
    if str(migration)!="20261104_0011":
        raise SystemExit("BLOCKER: unexpected Alembic revision")
    # Previously completed Game 84 settlement must remain exactly reconciled.
    game84=db.get(Game,84)
    if game84 is None or str(game84.status)!="ENDED":
        raise SystemExit("BLOCKER: previously refunded Game 84 not ENDED")
    refunds=db.execute(select(WalletTx).where(WalletTx.id.in_([338,339]))).scalars().all()
    if len(refunds)!=2 or sum(int(x.amount) for x in refunds)!=36000:
        raise SystemExit("BLOCKER: Game 84 refund ledger mismatch")
    if any(
        str(x.direction)!="CREDIT" or str(x.reason)!="ADJUST"
        or str(x.ref_type)!="GAME" or int(x.ref_id or 0)!=84
        for x in refunds
    ):
        raise SystemExit("BLOCKER: Game 84 refund ledger identity mismatch")
    keys=["bank_deposit_enabled","crypto_payments_runtime_enabled","deposit_destinations"]
    values={}
    for key in keys:
        row=db.get(AppSetting,key)
        values[key]=row.v_json if row is not None else None
    snapshot={
        "flags": flags,
        "settings": values,
        "crypto_tron": cfg.CRYPTO_TRON_USDT_ADDRESS,
        "crypto_ton": cfg.CRYPTO_TON_ADDRESS,
        "crypto_master": bool(cfg.CRYPTO_PAYMENTS_ENABLED),
    }
    digest=hashlib.sha256(
        json.dumps(snapshot,sort_keys=True,ensure_ascii=False,default=str).encode()
    ).hexdigest()
    def count(model):
        return int(db.execute(select(func.count()).select_from(model)).scalar_one())
    def count_pending(model,statuses):
        return int(db.execute(select(func.count()).select_from(model).where(
            model.status.in_(statuses)
        )).scalar_one())
    print("FINANCE_READONLY:",
          "wallets="+str(count(Wallet)),
          "ledger="+str(count(WalletTx)),
          "pending_bank="+str(count_pending(DepositRequest,["AWAITING_RECEIPT","PENDING_REVIEW"])),
          "pending_withdraw="+str(count_pending(WithdrawRequest,["PENDING"])),
          "pending_crypto="+str(count_pending(CryptoDepositRequest,["WAITING_PAYMENT","CONFIRMING"])),
          "active_games="+str(count_pending(Game,["LOBBY","RUNNING"])))
    print("RUNTIME_SHA="+digest)
PY
}
echo "===== READ-ONLY FINANCIAL + RUNTIME PREFLIGHT ====="
BEFORE="$(runtime_snapshot)"
printf '%s\n' "$BEFORE"
BEFORE_SHA="$(printf '%s\n' "$BEFORE" | sed -n 's/^RUNTIME_SHA=//p')"
[[ "$BEFORE_SHA" =~ ^[a-f0-9]{64}$ ]] || fail "invalid runtime fingerprint"

mkdir -p -m 0700 "$BACKUP"
TMP="$(mktemp -d /tmp/davarna-forum-mini-release.XXXXXX)"
chmod 0700 "$TMP"
echo "===== BACKUP DATABASE AND RECEIPTS ====="
docker exec davarna-mysql sh -ec '
  export MYSQL_PWD="$MYSQL_PASSWORD"
  exec mysqldump -u"$MYSQL_USER" --single-transaction --skip-lock-tables \
    --quick --no-tablespaces "$MYSQL_DATABASE"
' | gzip -1 > "$BACKUP/database.sql.gz"
gzip -t "$BACKUP/database.sql.gz" || fail "database dump corrupt"
[[ "$(stat -c %s "$BACKUP/database.sql.gz")" -gt 2048 ]] || fail "DB dump unexpectedly small"
tar -czf "$BACKUP/storage.tar.gz" -C "$PROD" storage davarna-bot/storage
tar -tzf "$BACKUP/storage.tar.gz" >/dev/null || fail "storage archive corrupt"
(cd "$BACKUP"; sha256sum database.sql.gz storage.tar.gz > SHA256SUMS)
printf '%s\n' "$BEFORE" > "$BACKUP/runtime-before.txt"
cat > "$BACKUP/rollback.yml" <<'EOF'
services:
  backend:
    image: davarna-backend:rbac-pr14-e087c40bd471
  bot:
    image: davarna-bot:pr13-d9434cb10d71
EOF
cat > "$BACKUP/upgrade.yml" <<'EOF'
services:
  backend:
    image: davarna-backend:forum-mini-e7517922-stage2
  bot:
    image: davarna-bot:forum-mini-e7517922-stage2
EOF

export TAMBOLA_V2_BACKEND_IMAGE="$OLD_BACKEND"
export TAMBOLA_V2_BOT_IMAGE="$OLD_BOT"
export DAVARNA_UX5_BACKEND_IMAGE="$OLD_BACKEND"
export DAVARNA_UX5_BOT_IMAGE="$OLD_BOT"

echo "===== VERIFY EFFECTIVE COMPOSE: IMAGE ONLY ====="
compose_for backend "$BACKUP/upgrade.yml" config --format json > "$TMP/backend.json"
compose_for bot "$BACKUP/upgrade.yml" config --format json > "$TMP/bot.json"
python3 - "$TMP/backend.json" "$TMP/bot.json" "$NEW_BACKEND" "$NEW_BOT" <<'PY'
import json,subprocess,sys
def inspect(args):
    return json.loads(subprocess.check_output(args,text=True))[0]
def envmap(rows):
    return {s.split("=",1)[0]:s.split("=",1)[1] for s in (rows or []) if "=" in s}
for name,path,tag in (
    ("backend",sys.argv[1],sys.argv[3]),("bot",sys.argv[2],sys.argv[4])
):
    conf=json.load(open(path,encoding="utf-8"))["services"][name]
    live=inspect(["docker","inspect","davarna-"+name])
    image=inspect(["docker","image","inspect",tag])
    if conf.get("image")!=tag:
        raise SystemExit("BLOCKER: effective candidate image mismatch: "+name)
    env=envmap(image["Config"].get("Env") or [])
    for k,v in (conf.get("environment") or {}).items():
        if v is None: env.pop(k,None)
        else: env[k]=str(v)
    if env!=envmap(live["Config"].get("Env") or []):
        raise SystemExit("BLOCKER: environment differs for "+name)
    oldports={(p,b.get("HostIp") or "0.0.0.0",str(b.get("HostPort") or ""))
        for p,ls in (live["HostConfig"].get("PortBindings") or {}).items() for b in ls or []}
    newports={(str(p["target"])+"/"+str(p.get("protocol") or "tcp"),
               str(p.get("host_ip") or "0.0.0.0"),str(p["published"]))
        for p in conf.get("ports") or []}
    if oldports!=newports: raise SystemExit("BLOCKER: port drift for "+name)
    oldmounts={(v.get("Type"),v.get("Source"),v.get("Destination"),not v.get("RW",True))
        for v in live.get("Mounts") or []}
    newmounts={(v.get("type"),v.get("source"),v.get("target"),bool(v.get("read_only",False)))
        for v in conf.get("volumes") or []}
    if oldmounts!=newmounts: raise SystemExit("BLOCKER: mount drift for "+name)
    print("PASS:",name,"effective image-only config")
PY

echo "===== DEPLOY APPROVED BACKEND IMAGE ====="
STARTED=1
compose_for backend "$BACKUP/upgrade.yml" up -d --no-deps --no-build --force-recreate backend
ready=0
for _ in $(seq 1 40); do
  if [[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-backend 2>/dev/null || true)" == healthy ]] \
    && curl -fsS --max-time 5 http://127.0.0.1:18080/health/db >/dev/null; then
    ready=1; break
  fi
  sleep 2
done
(( ready==1 )) || fail "new backend health failed"
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$NEW_BACKEND_ID" ]] \
  || fail "running backend not pinned candidate"
docker exec davarna-backend grep -q 'superadmin-controls-stage-20261107' /app/app/static/mini/index.html \
  || fail "new Mini App assets not loaded"
curl -fsS --max-time 10 http://127.0.0.1:18080/mini/index.html \
  | grep -F 'superadmin-controls-stage-20261107' >/dev/null \
  || fail "Mini App web endpoint not updated"

echo "===== DEPLOY APPROVED BOT IMAGE ====="
BOT_STARTED=1
compose_for bot "$BACKUP/upgrade.yml" up -d --no-deps --no-build --force-recreate bot
ready=0
for _ in $(seq 1 40); do
  if [[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-bot 2>/dev/null || true)" == healthy ]]; then
    ready=1; break
  fi
  sleep 2
done
(( ready==1 )) || fail "new Bot health failed"
[[ "$(docker inspect -f '{{.Image}}' davarna-bot)" == "$NEW_BOT_ID" ]] \
  || fail "running Bot not pinned candidate"
docker exec davarna-bot python -c \
  'from bot.services.user_forum_navigation import group_guide_text; assert "تاپیک" in group_guide_text()' \
  || fail "Bot forum navigation module invalid"

echo "===== VERIFY RUNTIME FINANCIAL SETTINGS UNCHANGED ====="
AFTER="$(runtime_snapshot)"
printf '%s\n' "$AFTER"
AFTER_SHA="$(printf '%s\n' "$AFTER" | sed -n 's/^RUNTIME_SHA=//p')"
[[ "$AFTER_SHA" == "$BEFORE_SHA" ]] || fail "financial/crypto/Autopilot settings changed"
printf '%s\n' "$AFTER" > "$BACKUP/runtime-after.txt"

echo "===== PR18 + PR19 PRODUCTION DEPLOYED SUCCESSFULLY ====="
docker ps --filter name=davarna-backend --filter name=davarna-bot \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
echo "Protected backup and code-only rollback overlay: $BACKUP"
echo "Telegram guide not posted; AutoDraw/Autopilot and financial intake settings unchanged."
