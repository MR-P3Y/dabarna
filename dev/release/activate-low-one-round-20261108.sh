#!/usr/bin/env bash
# ONE controlled, real-money LOW game: single SYSTEM LOBBY, AUTO start, AUTO draw.
# No repeated rounds: scheduler is MANUAL before Autopilot runtime starts.
# Does not alter wallet balances, payment methods, crypto addresses or other lanes.
set -Eeuo pipefail
umask 077
ROOT=/opt/davarna-v2
PROD=/opt/davarna
SOURCE=e7517922f08685be99a8f55564da1ad22abeddac
BACKEND_IMAGE=davarna-backend:forum-mini-e7517922-stage2
BACKEND_ID=sha256:b6d2709c3f78ce946a90aeb1b2bd6774acfa6b72a88cd604c370842cc3824850
BOT_IMAGE=davarna-bot:forum-mini-e7517922-stage2
BOT_ID=sha256:dccabe74e0d5eaad8d2a2f7df8fc5d5b53a84cfe1d6f172475aaed8b93ca04e2
BASE=$PROD/docker-compose.yml
INACTIVE=$ROOT/deploy/tambola-v2-inactive.compose.yml
BASE_FILES=()
BACKUP=/root/davarna-v2-release-backups/low-single-round-$(date -u +%Y%m%dT%H%M%SZ)
PHASE=0
CREATED=0
GAME_ID=""

die() { echo "BLOCKER: $*" >&2; exit 2; }
[[ "${DAVARNA_LOW_ONE_ROUND_APPROVAL:-}" == "APPROVE_LOW_ONE_ROUND_PRODUCTION" ]] ||
  die "explicit user authorization required for single real-money LOW game"
[[ "$(id -u)" == 0 ]] || die "run as root on NODE2"
exec 9>/run/davarna-low-one-round-release.lock
flock -n 9 || die "another LOW launch process holds the lock"
cd "$ROOT"
git cat-file -e "$SOURCE^{commit}" || die "tested source unavailable"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$BACKEND_IMAGE" ]] ||
  die "Backend live image tag changed"
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$BACKEND_ID" ]] ||
  die "Backend live image digest changed"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == "$BOT_IMAGE" ]] ||
  die "Bot live image tag changed"
[[ "$(docker inspect -f '{{.Image}}' davarna-bot)" == "$BOT_ID" ]] ||
  die "Bot live image digest changed"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] ||
    die "unhealthy dependency: $c"
done
[[ "$(curl -fsS --max-time 8 http://127.0.0.1:18080/health/db)" == '{"ok":true}' ]] ||
  die "Backend DB health not OK"
(( $(df -Pk "$PROD" | awk 'NR==2 {print $4}') > 3 * 1024 * 1024 )) ||
  die "less than 3 GiB disk free"
(( $(awk '/^MemAvailable:/ {print $2}' /proc/meminfo) > 650 * 1024 )) ||
  die "less than 650 MiB free RAM"

# Preserve the exact current Compose layer chain, INCLUDING earlier release overlays.
# No unknown or missing files are silently accepted.
chain="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' davarna-backend)"
IFS=',' read -r -a BASE_FILES <<< "$chain"
(( ${#BASE_FILES[@]} >= 4 )) || die "live backend Compose chain unexpectedly short"
[[ "${BASE_FILES[0]}" == "$BASE" && "${BASE_FILES[1]}" == "$INACTIVE" ]] ||
  die "unexpected Compose base"
declare -A SEEN=()
valid_releases=0
for f in "${BASE_FILES[@]}"; do
  [[ "$f" == /* && -f "$f" && ! -L "$f" ]] || die "missing/unsafe Compose file: $f"
  [[ -z "${SEEN[$f]+set}" ]] || die "duplicate Compose layer: $f"
  SEEN[$f]=1
  case "$f" in
    "$BASE"|"$INACTIVE"|"$ROOT/dev/release/ux5-candidate.compose.yml"| \
    /root/davarna-v2-release-backups/tambola-v2-manual.compose.yml| \
    /root/davarna-v2-release-backups/pr13-d9434cb10d71-20261106T183004Z/upgrade.yml| \
    /root/davarna-v2-release-backups/rbac-pr14-e087c40bd471-20261106T193945Z/upgrade.yml) ;;
    /root/davarna-v2-release-backups/forum-mini-e7517922-*/rollback.yml)
      printf '%s\n' services: '  backend:' "    image: davarna-backend:rbac-pr14-e087c40bd471" \
        '  bot:' '    image: davarna-bot:pr13-d9434cb10d71' | cmp -s - "$f" ||
        die "unrecognized old release rollback layer"
      ;;
    /root/davarna-v2-release-backups/forum-mini-e7517922-*/upgrade.yml)
      printf '%s\n' services: '  backend:' "    image: $BACKEND_IMAGE" \
        '  bot:' "    image: $BOT_IMAGE" | cmp -s - "$f" ||
        die "unexpected release upgrade content"
      valid_releases=$((valid_releases+1))
      ;;
    *) die "unknown live Compose layer: $f";;
  esac
done
(( valid_releases==1 )) || die "expected one PR18/PR19 upgrade overlay"
[[ "${BASE_FILES[$((${#BASE_FILES[@]}-1))]}" == */forum-mini-e7517922-*/upgrade.yml ]] ||
  die "live Backend terminal Compose layer not PR18/PR19 release"
[[ -f "$PROD/.env.prod" ]] || die "production env file missing"

export TAMBOLA_V2_BACKEND_IMAGE="$BACKEND_IMAGE"
export TAMBOLA_V2_BOT_IMAGE="$BOT_IMAGE"
export DAVARNA_UX5_BACKEND_IMAGE="$BACKEND_IMAGE"
export DAVARNA_UX5_BOT_IMAGE="$BOT_IMAGE"

compose_backend() {
  local overlay="$1"; shift
  local -a args=()
  for f in "${BASE_FILES[@]}"; do args+=(-f "$f"); done
  (cd "$PROD"; docker compose -p davarna --env-file "$PROD/.env.prod" \
    "${args[@]}" -f "$overlay" "$@")
}
backend_health() {
  local i
  for i in $(seq 1 45); do
    if [[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-backend 2>/dev/null || true)" == healthy ]] &&
      [[ "$(docker inspect -f '{{.Image}}' davarna-backend 2>/dev/null || true)" == "$BACKEND_ID" ]] &&
      curl -fsS --max-time 4 http://127.0.0.1:18080/health/db >/dev/null; then return 0; fi
    sleep 2
  done
  return 1
}
finish() {
  local rc=$?
  trap - EXIT
  if (( rc != 0 && PHASE > 0 )); then
    echo "===== FAILED: TRY CODE-ONLY SAFE HOLD (Autopilot OFF) =====" >&2
    set +e
    if [[ -f "$BACKUP/hold.yml" ]]; then
      compose_backend "$BACKUP/hold.yml" up -d --no-deps --no-build --force-recreate backend
      backend_health
      echo "SAFE HOLD ATTEMPTED. Verify Backend/Bot status; game may exist in LOBBY." >&2
      echo "Do not delete/refund/modify real purchases automatically." >&2
    fi
    echo "If a game was created, it can require manual handling of customer funds." >&2
  fi
  exit "$rc"
}
trap finish EXIT

# No Production writes before this preflight succeeds.
audit_state() {
  docker exec -i davarna-backend python - <<'PY'
import json,hashlib
from sqlalchemy import func,select
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game import Game
from app.models.game_autopilot import GameAutopilotConfig
from app.models.wallet import Wallet,WalletTx
from app.models.game import GamePurchase
from app.models.settings import AppSetting
from app.models.user import User
from app.services.game_autopilot_config_service import GameAutopilotConfigService

if not cfg.GAME_TAMBOLA_V2_ENABLED or cfg.GAME_AUTO_DRAW_ENABLED or cfg.GAME_AUTOPILOT_RUNTIME_ENABLED:
    raise SystemExit("BLOCKER: baseline game runtime flags drifted")
if int(cfg.USER_FORUM_CHAT_ID or 0)!=-1003614031001 or \
    GameAutopilotConfigService.topic_id_for_level("LOW")!=6:
    raise SystemExit("BLOCKER: forum or LOW topic ID drifted")
uid=cfg.GAME_AUTOPILOT_SYSTEM_USER_ID
if not uid: raise SystemExit("BLOCKER: no designated Autopilot actor user")
with SessionLocal() as db:
    if str(db.connection().exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one())!="20261104_0011":
        raise SystemExit("BLOCKER: Alembic version changed")
    if not db.get(User,int(uid)): raise SystemExit("BLOCKER: Autopilot system actor not in Users")
    items=[GameAutopilotConfigService.serialize(x) for x in db.execute(select(GameAutopilotConfig)).scalars()]
    by={x["level"]:x for x in items}
    low=by.get("LOW")
    if not low or low["enabled"] or (low["scheduler_mode"],low["start_mode"],low["draw_mode"])!=("MANUAL","MANUAL","MANUAL"):
        raise SystemExit("BLOCKER: LOW config is not disabled/manual")
    if (low["card_price"],low["game_rule"],low["min_unique_players"],low["draw_interval_seconds"])!=(5000,"LINE",2,8):
        raise SystemExit("BLOCKER: LOW price/rule/minimum/draw interval drift")
    if abs(low["commission_rate"]-0.1)>0.000001 or low["countdown_seconds"]!=30:
        raise SystemExit("BLOCKER: LOW commission/countdown drift")
    if any(by.get(n,{}).get("enabled") for n in ("MEDIUM","HIGH")):
        raise SystemExit("BLOCKER: MEDIUM or HIGH enabled")
    active=db.execute(select(func.count()).select_from(Game).where(Game.status.in_(["LOBBY","RUNNING"]))).scalar_one()
    if active: raise SystemExit("BLOCKER: active game exists in Production")
    wallets=db.execute(select(func.count(),func.coalesce(func.sum(Wallet.balance),0))).one()
    protected={}
    for key in ("deposit_destinations","bank_deposit_enabled","crypto_payments_runtime_enabled"):
        row=db.get(AppSetting,key)
        protected[key]=row.v_json if row is not None else None
    protected.update(tron=cfg.CRYPTO_TRON_USDT_ADDRESS,ton=cfg.CRYPTO_TON_ADDRESS,
                     crypto_enabled=bool(cfg.CRYPTO_PAYMENTS_ENABLED))
    payment_sha=hashlib.sha256(json.dumps(protected,sort_keys=True,
                  ensure_ascii=False,default=str).encode()).hexdigest()
    print("PAYMENTS_SHA="+payment_sha)
    print("PASS: LOW disabled/manual, no active games, MEDIUM/HIGH off")
    print("BEFORE_WALLETS_COUNT="+str(int(wallets[0])))
    print("BEFORE_WALLETS_SUM="+str(int(wallets[1])))
    print("BEFORE_LEDGER_COUNT="+str(int(db.execute(select(func.count()).select_from(WalletTx)).scalar_one())))
    print("BEFORE_PURCHASE_COUNT="+str(int(db.execute(select(func.count()).select_from(GamePurchase)).scalar_one())))
PY
}
echo "===== CONFIRM SAFE LIVE GAME AND FINANCE BASELINE ====="
BEFORE="$(audit_state)" || die "launch preflight failed; zero writes"
printf '%s\n' "$BEFORE"
PAYMENTS_BEFORE_SHA="$(printf '%s\n' "$BEFORE" | sed -n 's/^PAYMENTS_SHA=//p')"
[[ "$PAYMENTS_BEFORE_SHA" =~ ^[0-9a-f]{64}$ ]] || die "payment configuration fingerprint missing"

[[ ! -e "$BACKUP" ]] || die "backup folder already exists: $BACKUP"
mkdir -p -m 0700 "$BACKUP"
echo "===== BACKUP PRODUCTION DB BEFORE GAME CREATION ====="
docker exec davarna-mysql sh -ec '
  export MYSQL_PWD="$MYSQL_PASSWORD"
  exec mysqldump -u"$MYSQL_USER" --single-transaction --skip-lock-tables \
    --quick --no-tablespaces "$MYSQL_DATABASE"
' | gzip -1 > "$BACKUP/database.sql.gz"
gzip -t "$BACKUP/database.sql.gz" || die "database backup corrupt"
[[ "$(stat -c %s "$BACKUP/database.sql.gz")" -gt 2048 ]] || die "database backup too small"
tar -czf "$BACKUP/storage.tar.gz" -C "$PROD" storage davarna-bot/storage
tar -tzf "$BACKUP/storage.tar.gz" >/dev/null || die "storage backup invalid"
(cd "$BACKUP"; sha256sum database.sql.gz storage.tar.gz > SHA256SUMS)
printf '%s\n' "$BEFORE" > "$BACKUP/baseline.txt"

cat > "$BACKUP/draw-only.yml" <<'EOF'
services:
  backend:
    environment:
      GAME_AUTO_DRAW_ENABLED: "true"
      GAME_AUTOPILOT_RUNTIME_ENABLED: "false"
EOF
cat > "$BACKUP/live.yml" <<'EOF'
services:
  backend:
    environment:
      GAME_AUTO_DRAW_ENABLED: "true"
      GAME_AUTOPILOT_RUNTIME_ENABLED: "true"
EOF
cat > "$BACKUP/hold.yml" <<'EOF'
services:
  backend:
    environment:
      GAME_AUTO_DRAW_ENABLED: "false"
      GAME_AUTOPILOT_RUNTIME_ENABLED: "false"
EOF

# Verify final effective config differs ONLY in exactly the two approved flags.
# No env values, secrets, token or finance settings are echoed.
echo "===== COMPARE COMPOSE FLAGS / PORTS / VOLUMES (READ ONLY) ====="
compose_backend "$BACKUP/draw-only.yml" config --format json > "$BACKUP/draw-only.json"
compose_backend "$BACKUP/live.yml" config --format json > "$BACKUP/live.json"
python3 - "$BACKUP/draw-only.json" "$BACKUP/live.json" <<'PY'
import json,subprocess,sys
original=json.loads(subprocess.check_output(["docker","inspect","davarna-backend"],text=True))[0]
img=json.loads(subprocess.check_output(["docker","image","inspect",original["Config"]["Image"]],text=True))[0]
def env_map(rows):return dict(x.split("=",1) for x in (rows or []) if "=" in x)
existing=env_map(original["Config"]["Env"])
stage_expected=dict(existing,GAME_AUTO_DRAW_ENABLED="true",GAME_AUTOPILOT_RUNTIME_ENABLED="false")
live_expected=dict(existing,GAME_AUTO_DRAW_ENABLED="true",GAME_AUTOPILOT_RUNTIME_ENABLED="true")
oldports={(p,b.get("HostIp") or "0.0.0.0",str(b.get("HostPort") or ""))
          for p,ls in (original["HostConfig"].get("PortBindings") or {}).items() for b in ls or []}
oldmount={(v.get("Type"),v.get("Source"),v.get("Destination"),not v.get("RW",True))
          for v in original.get("Mounts") or []}
for name,path,expected in [("draw-only",sys.argv[1],stage_expected),("live",sys.argv[2],live_expected)]:
    conf=json.load(open(path,encoding="utf-8"))["services"]["backend"]
    if conf.get("image")!=original["Config"]["Image"]:raise SystemExit("BLOCKER: image drift "+name)
    actual=env_map(img["Config"].get("Env") or [])
    for k,v in (conf.get("environment") or {}).items():
        if v is None:actual.pop(k,None)
        else:actual[k]=str(v)
    if actual!=expected:
        diff=sorted(k for k in set(actual)|set(expected) if actual.get(k)!=expected.get(k))
        raise SystemExit("BLOCKER: unexpected environment differences: "+",".join(diff))
    ports={(str(p["target"])+"/"+str(p.get("protocol") or "tcp"),
            str(p.get("host_ip") or "0.0.0.0"),str(p["published"]))
            for p in conf.get("ports") or []}
    volumes={(v.get("type"),v.get("source"),v.get("target"),bool(v.get("read_only",False)))
            for v in conf.get("volumes") or []}
    if ports!=oldports or volumes!=oldmount:raise SystemExit("BLOCKER: ports/mounts drift "+name)
    if conf.get("restart",original["HostConfig"]["RestartPolicy"]["Name"])!=original["HostConfig"]["RestartPolicy"]["Name"]:
        raise SystemExit("BLOCKER: restart policy drift")
    print("PASS: "+name+" overlay changes only approved game worker flags")
PY
rm -f "$BACKUP/draw-only.json" "$BACKUP/live.json"
echo "===== START AUTO DRAW WORKER, KEEP AUTOPILOT RUNTIME OFF ====="
PHASE=1
compose_backend "$BACKUP/draw-only.yml" up -d --no-deps --no-build --force-recreate backend
backend_health || die "Backend not healthy after enabling draw worker"
docker exec -i davarna-backend python - <<'PY'
from app.core import config as c
assert c.GAME_TAMBOLA_V2_ENABLED and c.GAME_AUTO_DRAW_ENABLED
assert not c.GAME_AUTOPILOT_RUNTIME_ENABLED
print("PASS: auto draw ready, Autopilot still OFF")
PY

echo "===== CREATE EXACTLY ONE SYSTEM LOW GAME, THEN FREEZE SCHEDULER ====="
# This is the FIRST intentional game DB write. The Autopilot worker is OFF
# while the scheduler is briefly AUTO to create one SYSTEM game.
result="$(
  docker exec -i davarna-backend python - <<'PY'
from sqlalchemy import select,func
from app.core import config as cfg
from app.core.admin_guard import AdminIdentity,AdminScope
from app.core.db import SessionLocal
from app.models.game import Game,GameAutoDraw
from app.models.game_autopilot import GameAutopilotConfig
from app.models.user import User
from app.services.admin_audit_service import AdminAuditService
from app.services.game_autopilot_config_service import GameAutopilotConfigService as CS
from app.services.game_autopilot_worker import GameAutopilotWorker

if cfg.GAME_AUTOPILOT_RUNTIME_ENABLED or not cfg.GAME_AUTO_DRAW_ENABLED:
    raise SystemExit("BLOCKER: unsafe worker state for one-shot create")
uid=int(cfg.GAME_AUTOPILOT_SYSTEM_USER_ID or 0)
actor=AdminIdentity(scope=AdminScope.SUPER_ADMIN,token="ONE_ROUND_RELEASE",user_id=uid)
with SessionLocal() as db:
    if db.get(User,uid) is None:raise SystemExit("BLOCKER: system actor missing")
    if int(db.execute(select(func.count()).select_from(Game).where(Game.status.in_(["LOBBY","RUNNING"]))).scalar_one())!=0:
        raise SystemExit("BLOCKER: existing active game")
    for level in ("MEDIUM","HIGH"):
        row=db.get(GameAutopilotConfig,level)
        if row is not None and int(row.enabled or 0):
            raise SystemExit("BLOCKER: another lane is enabled")
    low=CS.get(db,"LOW")
    if int(low.enabled or 0)!=0 or str(low.scheduler_mode)!="MANUAL" or str(low.start_mode)!="MANUAL" or str(low.draw_mode)!="MANUAL":
        raise SystemExit("BLOCKER: LOW config changed during backup")
    before,after=CS.update(db,level="LOW",values={
        "enabled":True,"scheduler_mode":"AUTO","start_mode":"AUTO","draw_mode":"AUTO"
    },updated_by=uid,allow_commission_change=False)
    AdminAuditService.record(db,admin=actor,action="autopilot.config.update",
        target_type="game_level",details={"level":"LOW","before":before,"after":after,
        "reason":"one-shot-authorized-production-low-launch"})
    db.commit()
state=None
try:
    # Executes the exact production Autopilot create path, one time.
    state=GameAutopilotWorker._run_level("LOW")
finally:
    # Runtime Autopilot is still OFF, so scheduler MANUAL reliably prevents
    # subsequent games; active SYSTEM LOBBY can still be managed when turned ON.
    with SessionLocal() as db:
        before,after=CS.update(db,level="LOW",values={"scheduler_mode":"MANUAL"},
            updated_by=uid,allow_commission_change=False)
        AdminAuditService.record(db,admin=actor,action="autopilot.config.update",
            target_type="game_level",details={"level":"LOW","before":before,"after":after,
            "reason":"freeze-future-rounds-before-worker-start"})
        db.commit()
if state!="created":
    raise SystemExit("BLOCKER: one-shot Autopilot did not create game; result="+str(state))
with SessionLocal() as db:
    active=db.execute(select(Game).where(Game.status.in_(["LOBBY","RUNNING"]))).scalars().all()
    if len(active)!=1:raise SystemExit("BLOCKER: expected one active game")
    game=active[0]
    control=db.get(GameAutoDraw,int(game.id))
    low=CS.get(db,"LOW")
    if (str(game.status),str(game.game_level),str(game.game_rule),
        int(game.card_price),str(game.draw_mode),str(game.execution_source),
        int(game.tg_topic_id or 0),int(game.tg_group_id))!=(
        "LOBBY","LOW","LINE",5000,"AUTO","SYSTEM",6,-1003614031001):
        raise SystemExit("BLOCKER: one-shot game state mismatch")
    if control is None or control.status!="ARMED" or int(control.interval_seconds)!=8 \
       or len(control.sequence_json)!=90 or len(set(control.sequence_json))!=90:
        raise SystemExit("BLOCKER: auto draw not armed correctly")
    if not int(low.enabled or 0) or low.scheduler_mode!="MANUAL" \
        or low.start_mode!="AUTO" or low.draw_mode!="AUTO":
        raise SystemExit("BLOCKER: scheduler not frozen")
    print("LOW_GAME_ID="+str(int(game.id)))
    print("PASS: exactly one SYSTEM LOW game, AUTO 8s numbers ARMED, repeat disabled")
PY
)" || die "game creation/inspection failed; check live DB, NEVER blindly rerun"
printf '%s\n' "$result"
GAME_ID="$(printf '%s\n' "$result" | sed -n 's/^LOW_GAME_ID=//p')"
[[ "$GAME_ID" =~ ^[1-9][0-9]*$ ]] || die "game creation may have succeeded without known ID"
CREATED=1
printf '%s\n' "$GAME_ID" > "$BACKUP/game-id.txt"

echo "===== ENABLE AUTOPILOT RUNTIME FOR EXISTING SINGLE GAME ====="
compose_backend "$BACKUP/live.yml" up -d --no-deps --no-build --force-recreate backend
backend_health || die "Backend unhealthy after Autopilot runtime enabled"
docker exec -i -e EXPECTED_GAME_ID="$GAME_ID" davarna-backend python - <<'PY'
import os
from sqlalchemy import select,func
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game import Game
from app.models.game_autopilot import GameAutopilotConfig
from app.models.wallet import Wallet,WalletTx
gid=int(os.environ["EXPECTED_GAME_ID"])
if not cfg.GAME_TAMBOLA_V2_ENABLED or not cfg.GAME_AUTO_DRAW_ENABLED or not cfg.GAME_AUTOPILOT_RUNTIME_ENABLED:
    raise SystemExit("BLOCKER: game worker runtime flags not active")
with SessionLocal() as db:
    low=db.get(GameAutopilotConfig,"LOW")
    if not low or not int(low.enabled or 0) or str(low.scheduler_mode)!="MANUAL" \
       or str(low.start_mode)!="AUTO" or str(low.draw_mode)!="AUTO":
        raise SystemExit("BLOCKER: repeat scheduler must be MANUAL")
    if any(int(db.get(GameAutopilotConfig,x).enabled or 0) for x in ("MEDIUM","HIGH")):
        raise SystemExit("BLOCKER: other lanes enabled")
    game=db.get(Game,gid)
    if game is None or game.status not in ("LOBBY","RUNNING") or game.execution_source!="SYSTEM":
        raise SystemExit("BLOCKER: created LOW game missing or unexpected")
    active=int(db.execute(select(func.count()).select_from(Game).where(Game.status.in_(["LOBBY","RUNNING"]))).scalar_one())
    if active!=1:raise SystemExit("BLOCKER: more than one active game")
    print("PASS: Single LOW game active, workers ready, no automatic next game")
    print("LIVE_GAME_ID="+str(gid))
PY

echo "===== PRODUCTION SINGLE LOW GAME IS READY ====="
echo "Live LOW game $GAME_ID, Telegram game topic 6, announce topic 3, live numbers 12, results 14."
echo "Start only after 2 DIFFERENT paying players; 30s countdown; random numbers every 8s."
echo "No next game automatically (scheduler_mode=MANUAL), MEDIUM/HIGH disabled."
echo "===== FINANCIAL ACTIVITY CHECK (READ ONLY) ====="
AFTER_FINANCE="$(docker exec -i davarna-backend python - <<'PY'
import hashlib,json
from sqlalchemy import func,select
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.settings import AppSetting
from app.models.wallet import Wallet,WalletTx
from app.models.game import GamePurchase
with SessionLocal() as db:
    row=db.execute(select(func.count(),func.coalesce(func.sum(Wallet.balance),0))).one()
    print("AFTER_WALLETS_COUNT="+str(int(row[0])))
    print("AFTER_WALLETS_SUM="+str(int(row[1])))
    print("AFTER_LEDGER_COUNT="+str(int(db.execute(select(func.count()).select_from(WalletTx)).scalar_one())))
    print("AFTER_PURCHASE_COUNT="+str(int(db.execute(select(func.count()).select_from(GamePurchase)).scalar_one())))
    protected={}
    for key in ("deposit_destinations","bank_deposit_enabled","crypto_payments_runtime_enabled"):
        item=db.get(AppSetting,key)
        protected[key]=item.v_json if item is not None else None
    protected.update(tron=cfg.CRYPTO_TRON_USDT_ADDRESS,ton=cfg.CRYPTO_TON_ADDRESS,
                     crypto_enabled=bool(cfg.CRYPTO_PAYMENTS_ENABLED))
    print("AFTER_PAYMENTS_SHA="+hashlib.sha256(json.dumps(protected,
          sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest())
PY
)" || die "post-launch financial check unavailable"
printf '%s\n' "$AFTER_FINANCE"
PAYMENTS_AFTER_SHA="$(printf '%s\n' "$AFTER_FINANCE" | sed -n 's/^AFTER_PAYMENTS_SHA=//p')"
[[ "$PAYMENTS_AFTER_SHA" == "$PAYMENTS_BEFORE_SHA" ]] || die "critical: payment settings drifted during LOW activation"
echo "PASS: bank/crypto payment settings unchanged"
echo "Compare BEFORE/AFTER finance counts; later user purchases can legitimately change balances."
echo "BACKUP_AND_HOLD_OVERLAY=$BACKUP"
echo "Do not rerun this launch command: a production game has been created."
