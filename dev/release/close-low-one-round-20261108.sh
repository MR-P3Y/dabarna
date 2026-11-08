#!/usr/bin/env bash
# Close out the already-settled LIVE LOW #85 rehearsal.
# Does NOT touch transactions, wallet balances, history, Telegram or game rows.
# It disables ONLY LOW autopilot config.enabled and both game worker ENV flags.
set -Eeuo pipefail
umask 077

PROD=/opt/davarna
ROOT=/opt/davarna-v2
GID=85
RELEASE=/root/davarna-v2-release-backups/low-single-round-20261108T003518Z
LIVE="$RELEASE/live.yml"
HOLD="$RELEASE/hold.yml"
BASE="$PROD/docker-compose.yml"
INACTIVE="$ROOT/deploy/tambola-v2-inactive.compose.yml"
BACKEND_TAG=davarna-backend:forum-mini-e7517922-stage2
BACKEND_ID=sha256:b6d2709c3f78ce946a90aeb1b2bd6774acfa6b72a88cd604c370842cc3824850
BOT_TAG=davarna-bot:forum-mini-e7517922-stage2
BOT_ID=sha256:dccabe74e0d5eaad8d2a2f7df8fc5d5b53a84cfe1d6f172475aaed8b93ca04e2
BACKUP=/root/davarna-v2-release-backups/low-close-85-$(date -u +%Y%m%dT%H%M%SZ)

# Compose JSON may embed production secrets. Always remove ephemeral config.
cleanup() { if [[ -n "${BACKUP:-}" && -d "$BACKUP" ]]; then rm -f -- "$BACKUP/hold-config.json"; fi; }
trap cleanup EXIT

die() { echo "BLOCKER: $*" >&2; exit 2; }
[[ "${DAVARNA_LOW_CLOSE_APPROVAL:-}" == "CLOSE_SETTLED_LOW_GAME_85" ]] ||
  die "explicit closeout approval gate missing"
[[ "$(id -u)" == 0 ]] || die "run as root"
exec 9>/run/davarna-low-one-round-release.lock
flock -n 9 || die "another LOW launch/close process holds lock"

[[ -f "$LIVE" && ! -L "$LIVE" && -f "$HOLD" && ! -L "$HOLD" ]] ||
  die "original release live/hold overlays missing"
printf '%s\n' services: '  backend:' '    environment:' \
  '      GAME_AUTO_DRAW_ENABLED: "true"' \
  '      GAME_AUTOPILOT_RUNTIME_ENABLED: "true"' | cmp -s - "$LIVE" ||
  die "live overlay not original version"
printf '%s\n' services: '  backend:' '    environment:' \
  '      GAME_AUTO_DRAW_ENABLED: "false"' \
  '      GAME_AUTOPILOT_RUNTIME_ENABLED: "false"' | cmp -s - "$HOLD" ||
  die "hold overlay not original version"
[[ "$(cat "$RELEASE/game-id.txt")" == "$GID" ]] || die "original released game ID mismatch"
cd "$ROOT"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$BACKEND_TAG" ]] ||
  die "backend tag drift"
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$BACKEND_ID" ]] ||
  die "backend image bytes drift"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == "$BOT_TAG" ]] ||
  die "bot tag drift"
[[ "$(docker inspect -f '{{.Image}}' davarna-bot)" == "$BOT_ID" ]] ||
  die "bot image bytes drift"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] ||
    die "unhealthy container: $c"
done

# Retain the exact current Compose chain (including live.yml).
chain="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' davarna-backend)"
IFS=',' read -r -a FILES <<< "$chain"
(( ${#FILES[@]} >= 5 )) || die "unexpected short backend Compose chain"
[[ "${FILES[0]}" == "$BASE" && "${FILES[1]}" == "$INACTIVE" ]] ||
  die "backend Compose base path drift"
[[ "${FILES[$((${#FILES[@]}-1))]}" == "$LIVE" ]] ||
  die "backend is not running original one-round live overlay"
declare -A SEEN=()
upgrade_count=0
for f in "${FILES[@]}"; do
  [[ "$f" == /* && -f "$f" && ! -L "$f" ]] || die "missing/unsafe Compose layer: $f"
  [[ -z "${SEEN[$f]+set}" ]] || die "duplicate Compose layer $f"
  SEEN[$f]=1
  case "$f" in
    "$BASE"|"$INACTIVE"|"$LIVE"| \
    "$ROOT/dev/release/ux5-candidate.compose.yml"| \
    /root/davarna-v2-release-backups/tambola-v2-manual.compose.yml| \
    /root/davarna-v2-release-backups/pr13-d9434cb10d71-20261106T183004Z/upgrade.yml| \
    /root/davarna-v2-release-backups/rbac-pr14-e087c40bd471-20261106T193945Z/upgrade.yml) ;;
    /root/davarna-v2-release-backups/forum-mini-e7517922-*/rollback.yml)
      printf '%s\n' services: '  backend:' "    image: davarna-backend:rbac-pr14-e087c40bd471" \
        '  bot:' '    image: davarna-bot:pr13-d9434cb10d71' | cmp -s - "$f" ||
        die "unexpected prior rollback content"
      ;;
    /root/davarna-v2-release-backups/forum-mini-e7517922-*/upgrade.yml)
      printf '%s\n' services: '  backend:' "    image: $BACKEND_TAG" \
        '  bot:' "    image: $BOT_TAG" | cmp -s - "$f" ||
        die "unexpected prior upgrade content"
      upgrade_count=$((upgrade_count+1))
      ;;
    *) die "unexpected Compose layer: $f";;
  esac
done
(( upgrade_count==1 )) || die "unexpected release upgrade count"
[[ -f "$PROD/.env.prod" ]] || die "Production .env.prod missing"

export TAMBOLA_V2_BACKEND_IMAGE="$BACKEND_TAG"
export TAMBOLA_V2_BOT_IMAGE="$BOT_TAG"
export DAVARNA_UX5_BACKEND_IMAGE="$BACKEND_TAG"
export DAVARNA_UX5_BOT_IMAGE="$BOT_TAG"

compose_backend() {
  local -a args=()
  for f in "${FILES[@]}"; do args+=(-f "$f"); done
  (cd "$PROD"; docker compose -p davarna --env-file "$PROD/.env.prod" \
    "${args[@]}" -f "$HOLD" "$@")
}
audit() {
  docker exec -i davarna-backend python - <<'PY'
import hashlib,json
from sqlalchemy import func,select
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game import Game,GameAutoDraw,GameCard,GameCalledNumber,GamePurchase
from app.models.game_autopilot import GameAutopilotConfig
from app.models.wallet import Wallet,WalletTx
from app.models.settings import AppSetting
from app.services.game_autopilot_config_service import GameAutopilotConfigService
if not cfg.GAME_TAMBOLA_V2_ENABLED:
    raise SystemExit("BLOCKER: V2 flag disabled")
if not cfg.GAME_AUTO_DRAW_ENABLED or not cfg.GAME_AUTOPILOT_RUNTIME_ENABLED:
    raise SystemExit("BLOCKER: game workers not in expected pre-close state")
with SessionLocal() as db:
    rev=str(db.connection().exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one())
    if rev!="20261104_0011":raise SystemExit("BLOCKER: unexpected migration revision")
    g=db.get(Game,85); a=db.get(GameAutoDraw,85)
    if not g or not a or str(g.status)!="ENDED" or str(a.status)!="STOPPED":
        raise SystemExit("BLOCKER: game #85 not fully completed")
    if (str(g.game_rule),str(g.game_level),str(g.draw_mode),int(g.card_price),
        str(g.execution_source),int(g.tg_topic_id or 0))!=("LINE","LOW","AUTO",5000,"SYSTEM",6):
        raise SystemExit("BLOCKER: #85 game identifiers/rules drift")
    numbers=db.execute(select(GameCalledNumber.number).where(GameCalledNumber.game_id==85)).scalars().all()
    if len(numbers)!=42 or len(set(numbers))!=42 or int(a.cursor)!=42:
        raise SystemExit("BLOCKER: #85 number count or draw cursor changed")
    purchases=db.execute(select(GamePurchase).where(GamePurchase.game_id==85)).scalars().all()
    players=int(db.execute(select(func.count(func.distinct(GameCard.user_id))).where(GameCard.game_id==85)).scalar_one())
    if len(purchases)!=2 or sum(int(p.total_price) for p in purchases)!=10000 or players!=2:
        raise SystemExit("BLOCKER: #85 purchases or unique player count mismatched")
    if int(g.sold_amount)!=10000 or int(g.prize_pool)!=9000 or int(g.commission_amount)!=1000:
        raise SystemExit("BLOCKER: #85 financial game totals drift")
    prizes=db.execute(select(WalletTx).where(WalletTx.ref_type=="GAME",WalletTx.ref_id==85,
        WalletTx.direction=="CREDIT",WalletTx.reason.in_(["PRIZE_COL","PRIZE_ROW"]))).scalars().all()
    by_reason={r:sum(int(t.amount) for t in prizes if str(t.reason)==r) for r in ("PRIZE_COL","PRIZE_ROW")}
    if len(prizes)!=2 or by_reason!={"PRIZE_COL":3000,"PRIZE_ROW":6000} or \
       len({(int(t.wallet_id),str(t.idempotency_key)) for t in prizes})!=2:
        raise SystemExit("BLOCKER: #85 prize split, unique payment keys or count mismatch")
    active=int(db.execute(select(func.count()).select_from(Game).where(Game.status.in_(["LOBBY","RUNNING"]))).scalar_one())
    newer=int(db.execute(select(func.count()).select_from(Game).where(Game.id>85,Game.game_level=="LOW")).scalar_one())
    if active!=0 or newer!=0:raise SystemExit("BLOCKER: newer LOW or active game detected")
    low=db.get(GameAutopilotConfig,"LOW")
    if not low or (int(low.enabled or 0),str(low.scheduler_mode),
                   str(low.start_mode),str(low.draw_mode))!=(1,"MANUAL","AUTO","AUTO"):
        raise SystemExit("BLOCKER: unexpected LOW enabled/modes")
    if any(int(db.get(GameAutopilotConfig,l).enabled or 0) for l in ("MEDIUM","HIGH")):
        raise SystemExit("BLOCKER: other autopilot lanes enabled")
    protected={}
    for key in ("deposit_destinations","bank_deposit_enabled","crypto_payments_runtime_enabled"):
        row=db.get(AppSetting,key)
        protected[key]=row.v_json if row is not None else None
    protected.update(tron=cfg.CRYPTO_TRON_USDT_ADDRESS,ton=cfg.CRYPTO_TON_ADDRESS,
                     crypto_enabled=bool(cfg.CRYPTO_PAYMENTS_ENABLED))
    digest=hashlib.sha256(json.dumps(protected,sort_keys=True,ensure_ascii=False,
                                 default=str).encode()).hexdigest()
    wallet_total=int(db.execute(select(func.coalesce(func.sum(Wallet.balance),0))).scalar_one())
    print("PASS: #85 ENDED/STOPPED, 42 unique numbers, purchase 10000, split 3000/6000")
    print("PASS: no new/active LOW; other levels off; repeat scheduler MANUAL")
    print("PAYMENTS_SHA="+digest)
    print("WALLETS_SUM="+str(wallet_total))
    print("TX_COUNT="+str(int(db.execute(select(func.count()).select_from(WalletTx)).scalar_one())))
PY
}
echo "===== VERIFY SETTLED GAME & FINANCE READ-ONLY ====="
BEFORE="$(audit)" || die "final game audit failed, no changes made"
printf '%s\n' "$BEFORE"
BEFORE_PAYMENTS_SHA="$(printf '%s\n' "$BEFORE" | sed -n 's/^PAYMENTS_SHA=//p')"
[[ "$BEFORE_PAYMENTS_SHA" =~ ^[a-f0-9]{64}$ ]] || die "missing payment fingerprint"

# Verify effective Compose settings are exactly the LIVE backend settings
# except flipping the two named game worker flags OFF. Do not show secrets.
echo "===== VERIFY HOLD COMPOSE EFFECTIVE CONFIG (READ ONLY) ====="
mkdir -p -m 0700 "$BACKUP"
compose_backend config --format json > "$BACKUP/hold-config.json" ||
  die "hold Compose config not valid"
python3 - "$BACKUP/hold-config.json" <<'PY'
import json,subprocess,sys
live=json.loads(subprocess.check_output(["docker","inspect","davarna-backend"],text=True))[0]
img=json.loads(subprocess.check_output(["docker","image","inspect",live["Config"]["Image"]],text=True))[0]
conf=json.load(open(sys.argv[1],encoding="utf8"))["services"]["backend"]
def env_map(items):return dict(x.split("=",1) for x in (items or []) if "=" in x)
expected=env_map(live["Config"]["Env"])
expected.update(GAME_AUTO_DRAW_ENABLED="false",GAME_AUTOPILOT_RUNTIME_ENABLED="false")
actual=env_map(img["Config"].get("Env") or [])
for k,v in (conf.get("environment") or {}).items():
    if v is None:actual.pop(k,None)
    else:actual[k]=str(v)
if conf.get("image")!=live["Config"]["Image"]:raise SystemExit("BLOCKER: backend image drift")
if actual!=expected:
    differences=sorted(k for k in set(actual)|set(expected) if actual.get(k)!=expected.get(k))
    raise SystemExit("BLOCKER: env differences other than worker flags: "+",".join(differences))
oldports={(p,b.get("HostIp") or "0.0.0.0",str(b.get("HostPort") or ""))
          for p,ls in (live["HostConfig"].get("PortBindings") or {}).items() for b in ls or []}
ports={(str(p["target"])+"/"+str(p.get("protocol") or "tcp"),
        str(p.get("host_ip") or "0.0.0.0"),str(p["published"]))
        for p in (conf.get("ports") or [])}
oldvol={(v.get("Type"),v.get("Source"),v.get("Destination"),not v.get("RW",True))
        for v in (live.get("Mounts") or [])}
vol={(v.get("type"),v.get("source"),v.get("target"),bool(v.get("read_only",False)))
        for v in (conf.get("volumes") or [])}
if ports!=oldports or vol!=oldvol:raise SystemExit("BLOCKER: ports/volumes drift")
if conf.get("restart",live["HostConfig"]["RestartPolicy"]["Name"])!=live["HostConfig"]["RestartPolicy"]["Name"]:
    raise SystemExit("BLOCKER: restart policy drift")
print("PASS: hold overlay changes ONLY GAME_AUTO_DRAW_ENABLED and GAME_AUTOPILOT_RUNTIME_ENABLED")
PY
rm -f "$BACKUP/hold-config.json"

echo "===== POST-GAME PRODUCTION DB BACKUP ====="
docker exec davarna-mysql sh -ec '
  export MYSQL_PWD="$MYSQL_PASSWORD"
  exec mysqldump -u"$MYSQL_USER" --single-transaction --skip-lock-tables --quick \
    --no-tablespaces "$MYSQL_DATABASE"
' | gzip -1 > "$BACKUP/after-game85.sql.gz"
gzip -t "$BACKUP/after-game85.sql.gz" || die "bad backup compression"
[[ "$(stat -c %s "$BACKUP/after-game85.sql.gz")" -gt 2048 ]] ||
  die "post-game backup too small"
(cd "$BACKUP"; sha256sum after-game85.sql.gz > SHA256SUMS)
printf '%s\n' "$BEFORE" > "$BACKUP/pre-close-readonly.txt"

echo "===== DISABLE ONLY LOW CONFIG.ENABLED; AUDIT CONTROL CHANGE ====="
docker exec -i davarna-backend python - <<'PY'
from sqlalchemy import select,func
from app.core import config as cfg
from app.core.admin_guard import AdminIdentity,AdminScope
from app.core.db import SessionLocal
from app.models.game import Game
from app.models.game_autopilot import GameAutopilotConfig
from app.services.admin_audit_service import AdminAuditService
from app.services.game_autopilot_config_service import GameAutopilotConfigService as CS
uid=int(cfg.GAME_AUTOPILOT_SYSTEM_USER_ID or 0)
if not uid:raise SystemExit("BLOCKER: no Autopilot system user")
actor=AdminIdentity(scope=AdminScope.SUPER_ADMIN,token="LOW_CLOSE_APPROVED",user_id=uid)
with SessionLocal() as db:
    count=int(db.execute(select(func.count()).select_from(Game)
        .where(Game.status.in_(["LOBBY","RUNNING"]))).scalar_one())
    if count:raise SystemExit("BLOCKER: active game appeared before disabling LOW")
    row=db.get(GameAutopilotConfig,"LOW")
    if not row or int(row.enabled or 0)!=1 or str(row.scheduler_mode)!="MANUAL":
        raise SystemExit("BLOCKER: LOW config changed before write")
    before,after=CS.update(db,level="LOW",values={"enabled":False},updated_by=uid,
        allow_commission_change=False)
    AdminAuditService.record(db,admin=actor,action="autopilot.config.update",
        target_type="game_level",details={"level":"LOW","before":before,"after":after,
          "reason":"confirmed settled one-round game 85; shut down test runtime"})
    db.commit()
    print("PASS: LOW.enabled=false; scheduler unchanged MANUAL; financial tables untouched")
PY

echo "===== DISABLE AUTO DRAW AND AUTOPILOT RUNTIME (BACKEND ONLY) ====="
compose_backend up -d --no-deps --no-build --force-recreate backend ||
  die "Backend update failed after LOW disabled; do NOT rerun blindly"
healthy=false
for i in $(seq 1 45); do
  if [[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-backend 2>/dev/null || true)" == healthy ]] &&
     [[ "$(docker inspect -f '{{.Image}}' davarna-backend 2>/dev/null || true)" == "$BACKEND_ID" ]] &&
      curl -fsS --max-time 4 http://127.0.0.1:18080/health/db >/dev/null 2>&1; then
    healthy=true
    break
  fi
  sleep 2
done
[[ "$healthy" == true ]] ||
  die "Backend failed to reach healthy after disabling workers; inspect immediately"

echo "===== VERIFY POST-CLOSE LIVE GAME, WORKERS & PAYMENTS READ-ONLY ====="
AFTER="$(docker exec -i davarna-backend python - <<'PY'
import hashlib,json
from sqlalchemy import select,func
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game import Game,GameAutoDraw,GameCalledNumber
from app.models.wallet import Wallet,WalletTx
from app.models.game_autopilot import GameAutopilotConfig
from app.models.settings import AppSetting
if not cfg.GAME_TAMBOLA_V2_ENABLED or cfg.GAME_AUTO_DRAW_ENABLED or cfg.GAME_AUTOPILOT_RUNTIME_ENABLED:
    raise SystemExit("BLOCKER: game runtime flags not safely disabled")
with SessionLocal() as db:
    g=db.get(Game,85); a=db.get(GameAutoDraw,85)
    l=db.get(GameAutopilotConfig,"LOW")
    if not g or not a or not l or g.status!="ENDED" or a.status!="STOPPED":
        raise SystemExit("BLOCKER: historical game 85 changed")
    if int(l.enabled or 0)!=0 or l.scheduler_mode!="MANUAL":
        raise SystemExit("BLOCKER: LOW not disabled")
    if any(int(db.get(GameAutopilotConfig,n).enabled or 0) for n in ("MEDIUM","HIGH")):
        raise SystemExit("BLOCKER: other autopilot levels enabled")
    active=int(db.execute(select(func.count()).select_from(Game).where(Game.status.in_(["LOBBY","RUNNING"]))).scalar_one())
    newer=int(db.execute(select(func.count()).select_from(Game).where(Game.id>85,Game.game_level=="LOW")).scalar_one())
    numbers=int(db.execute(select(func.count()).select_from(GameCalledNumber).where(GameCalledNumber.game_id==85)).scalar_one())
    prizes=db.execute(select(WalletTx).where(WalletTx.ref_type=="GAME",
        WalletTx.ref_id==85,WalletTx.direction=="CREDIT",
        WalletTx.reason.in_(["PRIZE_COL","PRIZE_ROW"]))).scalars().all()
    if active or newer or numbers!=42 or len(prizes)!=2 or sum(int(t.amount) for t in prizes)!=9000:
        raise SystemExit("BLOCKER: unexpected live game/payout status")
    protected={}
    for key in ("deposit_destinations","bank_deposit_enabled","crypto_payments_runtime_enabled"):
        row=db.get(AppSetting,key)
        protected[key]=row.v_json if row is not None else None
    protected.update(tron=cfg.CRYPTO_TRON_USDT_ADDRESS,ton=cfg.CRYPTO_TON_ADDRESS,
                     crypto_enabled=bool(cfg.CRYPTO_PAYMENTS_ENABLED))
    print("PAYMENTS_SHA="+hashlib.sha256(json.dumps(protected,
        sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest())
    print("WALLETS_SUM="+str(int(db.execute(select(func.coalesce(func.sum(Wallet.balance),0))).scalar_one())))
    print("TX_COUNT="+str(int(db.execute(select(func.count()).select_from(WalletTx)).scalar_one())))
    print("PASS: game85 ENDED 42 numbers 9000 paid; no game worker running; LOW disabled")
PY
)" || die "post-close read-only verification failed"
printf '%s\n' "$AFTER"
AFTER_PAYMENTS_SHA="$(printf '%s\n' "$AFTER" | sed -n 's/^PAYMENTS_SHA=//p')"
[[ "$AFTER_PAYMENTS_SHA" == "$BEFORE_PAYMENTS_SHA" ]] ||
  die "CRITICAL: bank/crypto settings changed unexpectedly; investigate"
echo "PASS: payment setup unchanged"
echo "===== LOW GAME 85 SAFELY CLOSED; BOTH AUTOMATIC WORKERS OFF ====="
echo "Production game history and payout records preserved."
echo "BACKUP=$BACKUP"
echo "No further production actions in this script."
