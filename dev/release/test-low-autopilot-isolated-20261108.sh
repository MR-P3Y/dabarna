#!/usr/bin/env bash
# LOW Autopilot launch rehearsal: test ONLY. No Production DB mutations,
# no compose changes, no Telegram, no runtime flag enabling.
set -Eeuo pipefail
umask 077

ROOT=/opt/davarna-v2
SOURCE=e7517922f08685be99a8f55564da1ad22abeddac
BACKEND_TAG=davarna-backend:forum-mini-e7517922-stage2
BACKEND_ID=sha256:b6d2709c3f78ce946a90aeb1b2bd6774acfa6b72a88cd604c370842cc3824850
BOT_TAG=davarna-bot:forum-mini-e7517922-stage2
BOT_ID=sha256:dccabe74e0d5eaad8d2a2f7df8fc5d5b53a84cfe1d6f172475aaed8b93ca04e2
TEST_DB=davarna_tambola_v2_test_20261104
WORK=""

fail() { echo "BLOCKER: $*" >&2; exit 2; }

[[ "$(id -u)" == 0 ]] || fail "run as root"
exec 9>/run/davarna-low-autopilot-isolated.lock
flock -n 9 || fail "another isolated LOW rehearsal is in progress"

cd "$ROOT"
git cat-file -e "$SOURCE^{commit}" || fail "approved release source absent"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-backend)" == "$BACKEND_TAG" ]] || fail "running Backend tag differs"
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$BACKEND_ID" ]] || fail "running Backend ID differs"
[[ "$(docker inspect -f '{{.Config.Image}}' davarna-bot)" == "$BOT_TAG" ]] || fail "running Bot tag differs"
[[ "$(docker inspect -f '{{.Image}}' davarna-bot)" == "$BOT_ID" ]] || fail "running Bot ID differs"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] || fail "unhealthy service: $c"
done
[[ "$(curl -fsS --max-time 8 http://127.0.0.1:18080/health/db)" == '{"ok":true}' ]] || fail "DB health endpoint failed"
[[ "$TEST_DB" == davarna_tambola_v2_test_20261104 ]] || fail "unexpected test DB"
(( $(awk '/^MemAvailable:/ {print $2}' /proc/meminfo) > 650 * 1024 )) || fail "available RAM below 650 MiB"
(( $(df -Pk "$ROOT" | awk 'NR==2 {print $4}') > 2 * 1024 * 1024 )) || fail "available disk below 2 GiB"

# Read only: protected configuration and aggregate finance baseline.
# No secret values, private wallet data, or crypto addresses are printed.
snapshot() {
  docker exec -i davarna-backend python - <<'PY'
import hashlib,json
from sqlalchemy import func,select
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game import Game,GamePurchase
from app.models.wallet import Wallet,WalletTx
from app.models.settings import AppSetting
from app.models.game_autopilot import GameAutopilotConfig
from app.services.game_autopilot_config_service import GameAutopilotConfigService
flags={"tambola_v2":bool(cfg.GAME_TAMBOLA_V2_ENABLED),
       "auto_draw":bool(cfg.GAME_AUTO_DRAW_ENABLED),
       "autopilot_runtime":bool(cfg.GAME_AUTOPILOT_RUNTIME_ENABLED)}
if flags != {"tambola_v2":True,"auto_draw":False,"autopilot_runtime":False}:
    raise SystemExit("BLOCKER: automatic game runtime is unexpectedly enabled")
with SessionLocal() as db:
    migration=str(db.connection().exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one())
    if migration!="20261104_0011":
        raise SystemExit("BLOCKER: DB schema head changed")
    cfgs=db.execute(select(GameAutopilotConfig).order_by(GameAutopilotConfig.level)).scalars().all()
    bylevel={str(c.level):GameAutopilotConfigService.serialize(c) for c in cfgs}
    low=bylevel.get("LOW")
    if not low or low["enabled"] or low["scheduler_mode"]!="MANUAL" \
      or low["start_mode"]!="MANUAL" or low["draw_mode"]!="MANUAL":
        raise SystemExit("BLOCKER: live LOW is not in expected disabled/manual state")
    if low["card_price"]!=5000 or abs(low["commission_rate"]-0.1)>0.000001 \
      or low["min_unique_players"]!=2 or low["topic_id"]!=6 or low["game_rule"]!="LINE":
        raise SystemExit("BLOCKER: live LOW pricing/rule/players/topic drift")
    active=int(db.execute(select(func.count()).select_from(Game)
      .where(Game.status.in_(["LOBBY","RUNNING"]))).scalar_one())
    if active!=0:
        raise SystemExit("BLOCKER: a live game is active; review before testing")
    keys=("bank_deposit_enabled","crypto_payments_runtime_enabled","deposit_destinations")
    settings={}
    for k in keys:
        row=db.get(AppSetting,k)
        settings[k]=row.v_json if row is not None else None
    protected={
        "flags":flags,"autopilot":bylevel,"payment":settings,
        "tron":cfg.CRYPTO_TRON_USDT_ADDRESS,"ton":cfg.CRYPTO_TON_ADDRESS,
        "crypto_enabled":bool(cfg.CRYPTO_PAYMENTS_ENABLED),
    }
    def count(model): return int(db.execute(select(func.count()).select_from(model)).scalar_one())
    finance={
        "wallets":count(Wallet),
        "wallet_balance_sum":int(db.execute(select(func.coalesce(func.sum(Wallet.balance),0))).scalar_one()),
        "wallet_txs":count(WalletTx),
        "game_purchases":count(GamePurchase),
        "active_games":active,
    }
    print("LOW_CONFIG="+json.dumps(low,sort_keys=True,ensure_ascii=False,default=str))
    print("FINANCE_AGG="+json.dumps(finance,sort_keys=True))
    print("PROTECTED_SHA="+hashlib.sha256(json.dumps(protected,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest())
PY
}
cleanup() {
  local rc=$?
  trap - EXIT
  if [[ -n "$WORK" && -d "$WORK" ]]; then rm -rf -- "$WORK"; fi
  if [[ -n "${BEFORE_SHA:-}" ]]; then
    echo "===== POST-TEST PRODUCTION READ-ONLY RECHECK ====="
    set +e
    AFTER="$(snapshot)"
    recheck_rc=$?
    if (( recheck_rc == 0 )); then
      printf '%s\n' "$AFTER"
      AFTER_SHA="$(printf '%s\n' "$AFTER" | sed -n 's/^PROTECTED_SHA=//p')"
      if [[ "$BEFORE_SHA" != "$AFTER_SHA" ]]; then
        echo "WARNING: protected live configuration drift; investigate. NO production changes made by test runner." >&2
        rc=3
      elif [[ "${BEFORE_FINANCE:-}" != "$(printf '%s\n' "$AFTER" | sed -n 's/^FINANCE_AGG=//p')" ]]; then
        echo "WARNING: live finance totals changed while tests ran; inspect legitimate concurrent activity." >&2
        rc=3
      else
        echo "PASS: protected live config and aggregate finance values unchanged"
      fi
    else
      echo "WARNING: post-test production audit failed; inspect live service" >&2
      rc=3
    fi
  fi
  exit "$rc"
}
trap cleanup EXIT

echo "===== PROD STATE BEFORE (READ ONLY) ====="
BEFORE="$(snapshot)" || fail "Production snapshot failed"
printf '%s\n' "$BEFORE"
BEFORE_SHA="$(printf '%s\n' "$BEFORE" | sed -n 's/^PROTECTED_SHA=//p')"
BEFORE_FINANCE="$(printf '%s\n' "$BEFORE" | sed -n 's/^FINANCE_AGG=//p')"
[[ "$BEFORE_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "protected fingerprint missing"

# Confirm the separate test schema already exists. NEVER create or migrate DBs here.
echo "===== VERIFY ISOLATED MYSQL SCHEMA EXISTS ====="
docker exec davarna-mysql sh -ec '
  export MYSQL_PWD="$MYSQL_PASSWORD"
  mysql -u"$MYSQL_USER" --batch --skip-column-names \
    -e "SELECT schema_name FROM information_schema.schemata WHERE schema_name = '\''davarna_tambola_v2_test_20261104'\''"
' | grep -Fx "$TEST_DB" >/dev/null || fail "isolated test schema missing: do NOT use Production DB"

WORK="$(mktemp -d /tmp/davarna-low-e2e.XXXXXX)"
chmod 0700 "$WORK"
mkdir -p "$WORK/tests"
git archive "$SOURCE" -- \
  backend/tests/mysql_autopilot_e2e.py \
  backend/tests/test_autopilot_lifecycle_guards.py \
  backend/tests/test_autopilot_commission_rbac.py \
  backend/tests/test_game_auto_draw.py \
  backend/tests/test_game_finance_idempotency.py \
  | tar -x -C "$WORK"
cp -a "$WORK/backend/tests/." "$WORK/tests/"
rm -rf -- "$WORK/backend"
chmod 0644 "$WORK/tests/"*.py

python3 - "$WORK/test-db.env" <<'PY'
import json,os,subprocess,sys
from urllib.parse import urlsplit
obj=json.loads(subprocess.check_output(["docker","inspect","davarna-backend"],text=True))[0]
env=dict(item.split("=",1) for item in obj["Config"]["Env"] if "=" in item)
url=env.get("DATABASE_URL","")
if not url or not url.startswith(("mysql+","mysql://")):
    raise SystemExit("BLOCKER: Production MySQL URL missing; cannot copy credentials safely")
# E2E test replaces BOTH host and schema. Never expose credentials in output.
with open(sys.argv[1],"w",encoding="utf-8") as fp:
    fp.write("DATABASE_URL="+json.dumps(url)+"\n")
os.chmod(sys.argv[1],0o600)
PY

echo "===== 36? OFFLINE UNIT TESTS (NETWORK NONE, BUILT BACKEND) ====="
for pattern in \
  test_autopilot_lifecycle_guards.py \
  test_autopilot_commission_rbac.py \
  test_game_auto_draw.py \
  test_game_finance_idempotency.py
do
  docker run --rm --network none --read-only --memory 512m --cpus 1 \
    --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 \
    --tmpfs /tmp:rw,nosuid,nodev \
    --entrypoint python -w /app \
    -e DATABASE_URL='sqlite+pysqlite:///:memory:' \
    -e REDIS_URL='redis://127.0.0.1:6379/0' \
    -e RECEIPTS_DIR=/tmp/receipts -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$WORK/tests:/app/tests:ro" \
    "$BACKEND_TAG" -m unittest discover -s /app/tests -p "$pattern" -v
done

echo "===== REAL MYSQL E2E, TEST SCHEMA ONLY, OUTER ROLLBACK ====="
docker run --rm --network davarna_default --read-only --memory 512m --cpus 1 \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 \
  --tmpfs /tmp:rw,nosuid,nodev \
  --entrypoint python -w /app \
  -e DAVARNA_AUTOPILOT_E2E_DB="$TEST_DB" \
  -e RECEIPTS_DIR=/tmp/receipts -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$WORK/tests:/app/tests:ro" \
  -v "$WORK/test-db.env:/run/secrets/davarna_env:ro" \
  "$BACKEND_TAG" -m unittest discover -s /app/tests -p mysql_autopilot_e2e.py -v

echo "===== ISOLATED LOW AUTOPILOT REHEARSAL PASSED ====="
echo "Production game scheduler and AutoDraw remain disabled. No real cards were sold."
