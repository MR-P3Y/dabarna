#!/usr/bin/env bash
# FINANCE-REJECTION REGRESSION ONLY: no Production deploy, payment changes or
# wallet mutations. Separate test MySQL database, no real Telegram network.
set -Eeuo pipefail
umask 077
ROOT=/opt/davarna-v2
BRANCH=fix/mini-finance-rejection-reasons-20261108
TEST_DB=davarna_finance_reject_test_20261108
IMAGE=davarna-backend:forum-mini-e7517922-stage2
IMAGE_ID=sha256:b6d2709c3f78ce946a90aeb1b2bd6774acfa6b72a88cd604c370842cc3824850
WORK=""

die() { echo "BLOCKER: $*" >&2; exit 2; }
[[ "$(id -u)" == 0 ]] || die "root required"
[[ "${DAVARNA_FINANCE_REJECT_TEST_APPROVAL:-}" == "ISOLATED_TESTS_ONLY" ]] ||
  die "test-only approval env missing"
SOURCE="${DAVARNA_FINANCE_REJECT_SOURCE_SHA:-}"
[[ "$SOURCE" =~ ^[0-9a-f]{40}$ ]] || die "pinned branch SHA required"
exec 9>/run/davarna-finance-reject-tests.lock
flock -n 9 || die "finance rejection test already running"
cd "$ROOT"
git cat-file -e "$SOURCE^{commit}" || die "source SHA unavailable"
[[ "$(git rev-parse "origin/$BRANCH")" == "$SOURCE" ]] ||
  die "branch moved; pin reviewed source SHA"
[[ "$(docker image inspect -f '{{.Id}}' "$IMAGE")" == "$IMAGE_ID" ]] ||
  die "pinned base image unavailable"
for c in davarna-backend davarna-bot davarna-mysql davarna-redis; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" == healthy ]] ||
    die "unhealthy Production dependency: $c"
done
[[ "$(docker inspect -f '{{.Image}}' davarna-backend)" == "$IMAGE_ID" ]] ||
  die "Production backend image unexpectedly changed"
command -v node >/dev/null || die "node not installed"
(( $(awk '/^MemAvailable:/ {print $2}' /proc/meminfo) > 650 * 1024 )) ||
  die "less than 650 MiB free RAM"
(( $(df -Pk "$ROOT" | awk 'NR==2 {print $4}') > 2 * 1024 * 1024 )) ||
  die "less than 2 GiB free disk"

# Baseline reads ONLY the already-running Production image.
audit_production() {
docker exec -i davarna-backend python - <<'PY'
import hashlib,json
from sqlalchemy import select,func
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game import Game,GamePurchase
from app.models.wallet import Wallet,WalletTx
from app.models.finance import DepositRequest,WithdrawRequest
from app.models.settings import AppSetting
from app.models.game_autopilot import GameAutopilotConfig
flags=[bool(cfg.GAME_TAMBOLA_V2_ENABLED),bool(cfg.GAME_AUTO_DRAW_ENABLED),bool(cfg.GAME_AUTOPILOT_RUNTIME_ENABLED)]
if flags != [True,False,False]:
    raise SystemExit("BLOCKER: Production game runtime is not safely disabled")
with SessionLocal() as db:
    wallets=[(int(row[0]),int(row[1])) for row in db.execute(select(Wallet.user_id,Wallet.balance).order_by(Wallet.id))]
    sensitive={}
    for key in ("deposit_destinations","bank_deposit_enabled","crypto_payments_runtime_enabled"):
        r=db.get(AppSetting,key)
        sensitive[key]=r.v_json if r is not None else None
    sensitive.update(tron=cfg.CRYPTO_TRON_USDT_ADDRESS,ton=cfg.CRYPTO_TON_ADDRESS,
                     enabled=bool(cfg.CRYPTO_PAYMENTS_ENABLED))
    configs={c.level:{"enabled":int(c.enabled or 0),"scheduler":c.scheduler_mode,
              "start":c.start_mode,"draw":c.draw_mode} for c in db.execute(select(GameAutopilotConfig)).scalars()}
    if any(v["enabled"] for v in configs.values()):
        raise SystemExit("BLOCKER: Production autopilot level enabled")
    def count(model):
        return int(db.execute(select(func.count()).select_from(model)).scalar_one())
    statuses={}
    for model in (DepositRequest,WithdrawRequest):
        statuses[model.__tablename__]=[(str(x[0]),int(x[1])) for x in
          db.execute(select(model.status,func.count()).group_by(model.status)).all()]
    snapshot={
      "wallets_hash":hashlib.sha256(json.dumps(wallets).encode()).hexdigest(),
      "wallet_count":count(Wallet),"ledger":count(WalletTx),
      "purchases":count(GamePurchase),"games":count(Game),
      "statuses":statuses,
      "settings_sha":hashlib.sha256(json.dumps(sensitive,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest(),
      "flags":flags,"levels":configs,
    }
    print("PROD_READONLY="+json.dumps(snapshot,sort_keys=True,default=str))
PY
}
echo "===== PRODUCTION READ-ONLY BASELINE ====="
BEFORE="$(audit_production)" || die "failed Production preflight"
printf '%s\n' "$BEFORE"
[[ "$BEFORE" == PROD_READONLY=* ]] || die "production hash missing"
cleanup() { if [[ -n "$WORK" && -d "$WORK" ]]; then rm -rf -- "$WORK"; fi; }
trap cleanup EXIT
WORK="$(mktemp -d /tmp/davarna-finance-reject-XXXXXX)"
chmod 0700 "$WORK"
git archive "$SOURCE" -- backend | tar -x -C "$WORK"
test -f "$WORK/backend/tests/test_mini_deposit_rejection_reason.py" ||
  die "finance contract tests missing"
test -f "$WORK/backend/alembic/versions/20261108_0012_deposit_rejection_reason.py" ||
  die "required isolated migration missing"

echo "===== JAVASCRIPT PARSER / PYTHON AST (NO PRODUCTION WRITES) ====="
node --check "$WORK/backend/app/static/mini/app.js" || die "mini JS syntax failed"
python3 - "$WORK/backend" <<'PY'
import ast,pathlib,sys
root=pathlib.Path(sys.argv[1])
for rel in ("app/routers/mini_router.py","app/models/finance.py",
            "alembic/versions/20261108_0012_deposit_rejection_reason.py",
            "tests/test_mini_deposit_rejection_reason.py",
            "tests/mysql_mini_deposit_rejection_reason.py"):
    ast.parse((root / rel).read_text(encoding="utf8"),filename=rel)
print("PASS: finance Python syntax checked")
PY

echo "===== SQLITE UNIT TESTS (DISPOSABLE, NO NETWORK) ====="
for pattern in \
  test_mini_deposit_rejection_reason.py \
  test_mini_superadmin_ui_contract.py \
  test_game_finance_idempotency.py
do
  docker run --rm --network none --read-only --memory 512m --cpus 1 \
    --security-opt no-new-privileges --cap-drop ALL --pids-limit 128 \
    --tmpfs /tmp:rw,nosuid,nodev \
    -e DATABASE_URL='sqlite+pysqlite:///:memory:' \
    -e REDIS_URL='redis://127.0.0.1:6379/0' \
    -e RECEIPTS_DIR=/tmp/receipts -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$WORK/backend:/app:ro" --entrypoint python -w /app "$IMAGE" \
    -m unittest discover -s tests -p "$pattern" -v
done

echo "===== CREATE ISOLATED MYSQL TEST SCHEMA ONLY ====="
# A fresh named test DB is used rather than upgrading the older shared
# davarna_tambola_v2_test_20261104 schema. NO DROP/RENAME commands.
docker exec davarna-mysql sh -ec '
  test -n "$MYSQL_ROOT_PASSWORD"
  export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"
  mysql -uroot --batch --skip-column-names -e "
    CREATE DATABASE IF NOT EXISTS davarna_finance_reject_test_20261108
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  "
' || die "unable to create isolated test schema"

echo "===== PREPARE ROOT TEST DB URL (NO SECRETS PRINTED) ====="
python3 - "$WORK/mysql-finance.env" "$TEST_DB" <<'PY'
import json,os,subprocess,sys
from urllib.parse import quote,urlsplit,unquote
prod=json.loads(subprocess.check_output(["docker","inspect","davarna-backend"],text=True))[0]
production_env=dict(x.split("=",1) for x in prod["Config"]["Env"] if "=" in x)
production_url=production_env.get("DATABASE_URL","")
prod_name=unquote(urlsplit(production_url).path.lstrip("/"))
if not prod_name or prod_name==sys.argv[2] or prod_name.startswith("davarna_finance_reject_test_"):
    raise SystemExit("BLOCKER: unsafe Production/test database names")
mysql=json.loads(subprocess.check_output(["docker","inspect","davarna-mysql"],text=True))[0]
env=dict(x.split("=",1) for x in mysql["Config"]["Env"] if "=" in x)
pwd=env.get("MYSQL_ROOT_PASSWORD","")
if not pwd:
    raise SystemExit("BLOCKER: MySQL root credentials unavailable")
url="mysql+pymysql://root:"+quote(pwd,safe="")+"@davarna-mysql:3306/"+sys.argv[2]
with open(sys.argv[1],"w",encoding="utf8") as f:
    f.write("DATABASE_URL="+json.dumps(url)+"\n")
os.chmod(sys.argv[1],0o600)
print("PASS: private test DB URL produced; source is NOT Production")
PY

cat > "$WORK/test-finance-mysql.py" <<'PY'
import os,sys,unittest
from dotenv import dotenv_values
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from alembic.config import Config
from alembic import command

TEST="davarna_finance_reject_test_20261108"
if os.environ.get("DAVARNA_FINANCE_REJECT_TEST_DB")!=TEST:
    raise SystemExit("BLOCKER: opt-in test database flag missing")
dburl=dotenv_values("/run/secrets/mysql-finance.env").get("DATABASE_URL","")
if not dburl:
    raise SystemExit("BLOCKER: test database secret missing")
u=make_url(dburl)
if u.get_backend_name()!="mysql" or u.host!="davarna-mysql" or u.database!=TEST or u.username!="root":
    raise SystemExit("BLOCKER: non-isolated DB URL")
os.environ["DATABASE_URL"]=dburl
os.environ["REDIS_URL"]="redis://127.0.0.1:6379/0"
os.environ["GAME_AUTOPILOT_RUNTIME_ENABLED"]="false"
os.environ["GAME_AUTO_DRAW_ENABLED"]="false"

engine=create_engine(u,pool_pre_ping=True)
with engine.connect() as conn:
    name=conn.execute(text("SELECT DATABASE()")).scalar_one()
    if name!=TEST:raise SystemExit("BLOCKER: actual connected DB differs")
    existing=int(conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='alembic_version'"
    )).scalar_one())
    revision=conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() if existing else "EMPTY"
    if revision not in ("EMPTY","20261108_0012"):
        raise SystemExit("BLOCKER: unexpected test DB migration head "+str(revision))
engine.dispose()
if revision=="EMPTY":
    command.upgrade(Config("/app/alembic.ini"),"head")
    print("PASS: full Alembic migration applied to ISOLATED MySQL test database")
else:
    print("PASS: test DB already at expected isolated migration head")

loader=unittest.TestLoader()
suite=loader.discover("/app/tests",pattern="mysql_mini_deposit_rejection_reason.py")
if suite.countTestCases()<2:
    raise SystemExit("BLOCKER: expected MySQL finance tests not discovered")
result=unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful():raise SystemExit(1)
print("PASS: MySQL finance rejection idempotency/ledger/legacy tests (outer rollback)")
PY

echo "===== MYSQL E2E: ONLY FINANCE REJECTION TEST SCHEMA ====="
docker run --rm --network davarna_default --read-only --memory 512m --cpus 1 \
  --security-opt no-new-privileges --cap-drop ALL --pids-limit 128 \
  --tmpfs /tmp:rw,nosuid,nodev \
  -e DAVARNA_FINANCE_REJECT_TEST_DB="$TEST_DB" \
  -e RECEIPTS_DIR=/tmp/receipts -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$WORK/backend:/app:ro" \
  -v "$WORK/mysql-finance.env:/run/secrets/mysql-finance.env:ro" \
  -v "$WORK/test-finance-mysql.py:/tmp/test-finance-mysql.py:ro" \
  --entrypoint python -w /app "$IMAGE" /tmp/test-finance-mysql.py

echo "===== PRODUCTION READ-ONLY RECHECK ====="
AFTER="$(audit_production)" || die "Production post-test audit failed"
printf '%s\n' "$AFTER"
if [[ "$BEFORE" != "$AFTER" ]]; then
  echo "ALERT: Production balance/status/config snapshot changed while tests ran." >&2
  echo "This may be legitimate concurrent user activity; investigate before any release." >&2
  exit 3
fi
echo "===== PASS: ISOLATED FINANCE REJECTION TESTS; PRODUCTION UNCHANGED ====="
