#!/usr/bin/env bash
# Create only the OWNER identity in the private zero-km database.
# Read owner Telegram ID from the existing live owner (ID=4) after validating
# SUPER_ADMIN role, without copying old users, wallets, transactions or games.
# No bot start, no production writes, no payment changes, no secrets printed.
set -Eeuo pipefail
umask 077
die(){ echo "BLOCKED: $*" >&2; exit 2; }
[[ "${DAVARNA_ZERO_KM_OWNER_APPROVAL:-}" == "BOOTSTRAP_OWNER_ONLY_NEW_DB" ]] || die "owner-only approval missing"
[[ "$(id -u)" == 0 ]] || die "root required"

DB=davarna_zero_20261110
DB_CONTAINER=davarna-zero-mysql-20261110
API=davarna-zero-backend-preview-20261110
NEW_OWNER_ID=1
LIVE_OWNER_ID=4
SECRETS_DIR=/root/davarna-zero-km-20261110
OWNER_FILE="$SECRETS_DIR/owner-local.env"

[[ ! -e "$OWNER_FILE" ]] || die "owner-config file exists; no overwrite"
[[ "$(docker inspect -f '{{.State.Running}}' "$API")" == true ]] || die "private preview API not running"
[[ "$(docker inspect -f '{{.Image}}' "$API")" == "sha256:fc059ab62a9dde6a6f22447607fd13cd12f89cac0a7fd4a2b2949693bdbdccef" ]] || die "unexpected preview image"
[[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-backend)" == healthy ]] || die "live backend unhealthy"
[[ "$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER")" == true ]] || die "private fresh DB unavailable"

echo "===== VERIFY OWNER IDENTITY READ-ONLY ON CURRENT PRODUCTION ====="
OWNER_TG_ID="$(docker exec -i davarna-backend python - <<'PY'
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.user import User
from app.models.rbac import Role, UserRole
from sqlalchemy import select
assert cfg.RBAC_OWNER_USER_ID == 4, "current owner ID changed; stop"
with SessionLocal() as db:
    user=db.get(User, 4)
    assert user is not None and int(user.tg_user_id)>0, "current owner record missing"
    roles=db.execute(
        select(Role.name).join(UserRole, Role.id==UserRole.role_id)
        .where(UserRole.user_id==4)
    ).scalars().all()
    assert "SUPER_ADMIN" in roles, "current owner does not have persisted SUPER_ADMIN role"
    ids=getattr(cfg, "SUPER_ADMIN_TG_USER_IDS", set())
    assert not ids or int(user.tg_user_id) in ids, "current owner's Telegram ID not in configured super-admin list"
    print(int(user.tg_user_id))
PY
)"
[[ "$OWNER_TG_ID" =~ ^[1-9][0-9]{3,18}$ ]] || die "Telegram owner ID not verified"
echo "PASS: current owner Telegram identity and SUPER_ADMIN role verified (ID withheld)"

echo "===== GUARDED INSERT INTO PRIVATE FRESH DB ====="
docker exec -i -e "DAVARNA_BOOTSTRAP_TG_USER_ID=$OWNER_TG_ID" "$API" python - <<'PY'
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.user import User
from app.models.rbac import Role, UserRole
from app.models.wallet import Wallet, WalletTx
from app.models.game import Game, GamePurchase
from app.models.crypto import CryptoDepositRequest
from app.models.finance import DepositRequest, WithdrawRequest
from sqlalchemy import select,func
import os
from sqlalchemy.engine import make_url

url=make_url(cfg.DATABASE_URL)
assert url.database=="davarna_zero_20261110" and url.host=="davarna-zero-mysql-20261110", "Wrong target database"
assert not cfg.CRYPTO_PAYMENTS_ENABLED and not cfg.CRYPTO_AUTO_CONFIRM_ENABLED
assert not cfg.GAME_AUTO_DRAW_ENABLED and not cfg.GAME_AUTOPILOT_RUNTIME_ENABLED
tg=int(os.environ["DAVARNA_BOOTSTRAP_TG_USER_ID"])
with SessionLocal() as db:
    db.begin()
    tables=(User, UserRole, Wallet, WalletTx, Game, GamePurchase, CryptoDepositRequest, DepositRequest, WithdrawRequest)
    for table in tables:
        n=int(db.execute(select(func.count()).select_from(table)).scalar_one())
        assert n==0, f"{table.__tablename__} not empty: {n}"
    role=db.execute(select(Role).where(Role.name=="SUPER_ADMIN")).scalar_one()
    owner=User(id=1,tg_user_id=tg)
    db.add(owner)
    db.flush()
    db.add(UserRole(user_id=1,role_id=int(role.id)))
    db.flush()
    assert db.execute(select(func.count()).select_from(User)).scalar_one()==1
    assert db.execute(select(func.count()).select_from(UserRole)).scalar_one()==1
    for table in tables[2:]:
        assert db.execute(select(func.count()).select_from(table)).scalar_one()==0
    db.commit()
    print("PASS: fresh local user_id=1, SUPER_ADMIN role=1, no old wallet or financial records")
PY

# Retain owner-only configuration on host with strictly private permissions.
# Future production cutover MUST use RBAC_OWNER_USER_ID=1, NOT the old value 4.
printf 'RBAC_OWNER_USER_ID=%s\nSUPER_ADMIN_TG_USER_IDS=%s\n' \
  "$NEW_OWNER_ID" "$OWNER_TG_ID" > "$OWNER_FILE"
chmod 600 "$OWNER_FILE"

echo "===== ZERO-KM OWNER BOOTSTRAP PASS ====="
echo "OWNER_LOCAL_USER_ID=1"
echo "OWNER_ROLE=SUPER_ADMIN"
echo "OWNER_CONFIG_FILE=$OWNER_FILE (private; do not paste contents)"
echo "OLD_PRODUCTION_UNCHANGED=true"
echo "BOT_STARTED=false"
echo "PAYMENTS_ENABLED=false"
echo "NEXT=configure new wallet addresses and build isolated cutover package"
