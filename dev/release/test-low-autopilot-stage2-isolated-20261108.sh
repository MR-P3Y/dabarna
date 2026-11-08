#!/usr/bin/env bash
# LOW Autopilot release gate (TEST ONLY). Uses approved stage2 backend image.
# Unit tests: network disabled. MySQL E2E: fixed named isolated test DB only.
# Never touches Production config, wallets, tables or Autopilot flags.
set -Eeuo pipefail
umask 077

ROOT=/opt/davarna-v2
SOURCE=e7517922f08685be99a8f55564da1ad22abeddac
IMAGE=davarna-backend:forum-mini-e7517922-stage2
IMAGE_ID=sha256:b6d2709c3f78ce946a90aeb1b2bd6774acfa6b72a88cd604c370842cc3824850
TEST_DB=davarna_tambola_v2_test_20261104

fail() { echo "BLOCKER: $*" >&2; exit 2; }
[[ "$(id -u)" == 0 ]] || fail "root required"
exec 9>/run/davarna-low-autopilot-test.lock
flock -n 9 || fail "LOW isolated test already running"
cd "$ROOT"
git cat-file -e "$SOURCE^{commit}" || fail "source commit unavailable"
[[ "$(docker image inspect -f '{{.Id}}' "$IMAGE")" == "$IMAGE_ID" ]] \
  || fail "candidate image ID differs from previously tested stage2 image"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] \
    || fail "$c is not healthy"
done
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$IMAGE_ID" ]] \
  || fail "Production is not running approved stage2 Backend image"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == davarna-bot:forum-mini-e7517922-stage2 ]] \
  || fail "Production Bot tag unexpectedly changed"
available="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
(( available >= 650 * 1024 )) || fail "less than 650 MiB available RAM"

WORK="$(mktemp -d /tmp/davarna-low-autopilot-isolated.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
chmod 0700 "$WORK"
git archive "$SOURCE" -- \
  backend/tests/mysql_autopilot_e2e.py \
  backend/tests/test_autopilot_commission_rbac.py \
  backend/tests/test_autopilot_lifecycle_guards.py \
  backend/tests/test_game_auto_draw.py \
  backend/tests/test_game_finance_idempotency.py \
  backend/tests/test_game_commission.py \
  backend/tests/test_game_v2_dispatch.py | tar -x -C "$WORK"

echo "===== READ-ONLY PRODUCTION RUNTIME AND FINANCIAL BASELINE ====="
audit_live() {
  docker exec -i davarna-backend python - <<'PY'
from decimal import Decimal
from hashlib import sha256
from sqlalchemy import select, func
import json
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game_autopilot import GameAutopilotConfig
from app.models.game import Game
from app.models.wallet import Wallet, WalletTx
from app.models.settings import AppSetting

flags=[bool(cfg.GAME_TAMBOLA_V2_ENABLED),
       bool(cfg.GAME_AUTO_DRAW_ENABLED),
       bool(cfg.GAME_AUTOPILOT_RUNTIME_ENABLED)]
if flags != [True,False,False]:
    raise SystemExit("BLOCKER: Production runtime game flags changed")
with SessionLocal() as db:
    low=db.get(GameAutopilotConfig,"LOW")
    if low is None:
        raise SystemExit("BLOCKER: Production LOW configuration missing")
    if (int(low.enabled or 0)!=0 or str(low.scheduler_mode)!="MANUAL"
        or str(low.start_mode)!="MANUAL" or str(low.draw_mode)!="MANUAL"
        or int(low.card_price)!=5000 or Decimal(str(low.commission_rate))!=Decimal("0.1000")
        or int(low.min_unique_players)!=2):
        raise SystemExit("BLOCKER: Production LOW baseline changed")
    keys=["bank_deposit_enabled","crypto_payments_runtime_enabled","deposit_destinations"]
    settings={}
    for key in keys:
        r=db.get(AppSetting,key)
        settings[key]=r.v_json if r is not None else None
    rows=db.execute(select(GameAutopilotConfig)).scalars().all()
    safe_config={
        str(r.level): {k:str(getattr(r,k)) for k in (
           "enabled","scheduler_mode","start_mode","draw_mode",
           "card_price","commission_rate","announce_before_seconds",
           "countdown_seconds","repeat_interval_seconds",
           "draw_interval_seconds","cooldown_seconds","min_unique_players")}
        for r in rows
    }
    protected={"flags":flags,"game_configs":safe_config,"settings":settings,
        "tron":cfg.CRYPTO_TRON_USDT_ADDRESS,"ton":cfg.CRYPTO_TON_ADDRESS,
        "crypto_enabled":bool(cfg.CRYPTO_PAYMENTS_ENABLED)}
    total_wallets=int(db.execute(select(func.count()).select_from(Wallet)).scalar_one())
    total_ledger=int(db.execute(select(func.count()).select_from(WalletTx)).scalar_one())
    live_games=int(db.execute(select(func.count()).select_from(Game).where(
        Game.status.in_(["LOBBY","RUNNING"]))).scalar_one())
    # A check on live data that can distinguish test activity from changed Production data.
    wallets=db.execute(select(Wallet.user_id,Wallet.balance).order_by(Wallet.id)).all()
    financial_hash=sha256(json.dumps([(int(u),int(b)) for u,b in wallets]).encode()).hexdigest()
    output={"config_hash":sha256(json.dumps(protected,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest(),
            "wallet_hash":financial_hash,"wallets":total_wallets,"ledger":total_ledger,"active_games":live_games}
    print("PROD_READONLY_SNAPSHOT="+json.dumps(output,sort_keys=True))
PY
}
BEFORE="$(audit_live)" || fail "Production preflight audit failed"
printf '%s\n' "$BEFORE"
BASELINE="$(printf '%s\n' "$BEFORE" | sed -n 's/^PROD_READONLY_SNAPSHOT=//p')"
[[ -n "$BASELINE" ]] || fail "no baseline captured"

echo "===== RUN AUTOPILOT, DRAW, FINANCE & GAME UNIT TESTS: NO NETWORK ====="
for pattern in \
  'test_autopilot*.py' \
  'test_game_auto_draw.py' \
  'test_game_finance_idempotency.py' \
  'test_game_commission.py' \
  'test_game_v2_dispatch.py'
do
  docker run --rm --network none --read-only --memory 512m --cpus 1 \
    --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
    -e DATABASE_URL='sqlite+pysqlite:///:memory:' \
    -e REDIS_URL='redis://127.0.0.1:6379/0' \
    -e RECEIPTS_DIR='/tmp/receipts' -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$WORK/backend/tests:/app/tests:ro" \
    --entrypoint python -w /app "$IMAGE" \
    -m unittest discover -s /app/tests -p "$pattern" -v
done

echo "===== CONSTRUCT PRIVATE ISOLATED MYSQL TEST URL (NO CREDENTIAL OUTPUT) ====="
python3 - "$WORK/test-db.env" "$TEST_DB" <<'PY'
import json,os,subprocess,sys
from urllib.parse import urlsplit,unquote
obj=json.loads(subprocess.check_output(["docker","inspect","davarna-backend"],text=True))[0]
env=dict(e.split("=",1) for e in obj["Config"]["Env"] if "=" in e)
url=env.get("DATABASE_URL")
if not url:
    raise SystemExit("BLOCKER: DATABASE_URL missing from running Backend")
parts=urlsplit(url.replace("mysql+pymysql://","mysql://",1).replace("mysql+mysqlconnector://","mysql://",1))
db_name=unquote(parts.path.lstrip("/"))
if not parts.scheme.startswith("mysql") or not db_name or db_name==sys.argv[2]:
    raise SystemExit("BLOCKER: invalid Production DB source or test schema equals Production")
if db_name.startswith("davarna_tambola_v2_test_"):
    raise SystemExit("BLOCKER: source connection appears to point to a test database")
with open(sys.argv[1],"w",encoding="utf-8") as f:
    f.write("DATABASE_URL="+json.dumps(url)+"\n")
os.chmod(sys.argv[1],0o600)
print("PASS: Production DB source and isolated test DB are distinct; secrets not printed")
PY

echo "===== MYSQL E2E: 2 PLAYERS / BUY / AUTO START / 90 DRAWS / PAYOUT / REPEAT ====="
docker run --rm --network davarna_default --read-only --memory 512m --cpus 1 \
  --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
  -e DAVARNA_AUTOPILOT_E2E_DB="$TEST_DB" \
  -e RECEIPTS_DIR=/tmp/receipts -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$WORK/backend/tests:/app/tests:ro" \
  -v "$WORK/test-db.env:/run/secrets/davarna_env:ro" \
  --entrypoint python -w /app "$IMAGE" \
  -m unittest discover -s /app/tests -p mysql_autopilot_e2e.py -v

echo "===== READ-ONLY PRODUCTION RUNTIME AND FINANCIAL RECHECK ====="
AFTER="$(audit_live)" || fail "Production post-test audit failed"
printf '%s\n' "$AFTER"
AFTER_SNAPSHOT="$(printf '%s\n' "$AFTER" | sed -n 's/^PROD_READONLY_SNAPSHOT=//p')"
if [[ "$BASELINE" != "$AFTER_SNAPSHOT" ]]; then
  echo "ALERT: Production counters, wallet balances or configuration changed during isolated tests." >&2
  echo "This may be concurrent legitimate activity; review before enabling any feature." >&2
  exit 3
fi
echo "===== LOW AUTOPILOT ISOLATED TESTS PASSED; PRODUCTION UNCHANGED ====="
echo "LOW remains disabled; AutoDraw and Autopilot runtime remain disabled."
