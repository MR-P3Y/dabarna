#!/usr/bin/env bash
# Stage owner-supplied NEW public receive addresses for a FUTURE zero-km launch.
# Does NOT change live env, DB state, invoice issuance, scanning, or payment flags.
set -Eeuo pipefail
umask 077
die(){ echo "BLOCKED: $*" >&2; exit 2; }
[[ "${DAVARNA_ZERO_KM_STAGE_ADDRESSES_APPROVAL:-}" == "STAGE_VALIDATED_PUBLIC_RECEIVE_ADDRESSES_ONLY" ]] || die "stage-only approval missing"
[[ "$(id -u)" == 0 ]] || die "root required"
[[ -t 0 ]] || die "run interactively on NODE2; never send receiving addresses via command arguments"
DIR=/root/davarna-zero-km-20261110
DEST="$DIR/receiving-addresses.env"
IMAGE=davarna-backend:zero-km-combined-062cd58647d9
EXPECTED=sha256:fc059ab62a9dde6a6f22447607fd13cd12f89cac0a7fd4a2b2949693bdbdccef
API=davarna-zero-backend-preview-20261110
NEW_DB=davarna_zero_20261110
[[ ! -e "$DEST" ]] || die "addresses file already exists; no overwrite"
[[ "$(docker image inspect -f '{{.Id}}' "$IMAGE")" == "$EXPECTED" ]] || die "combined image changed"
[[ "$(docker inspect -f '{{.Image}}' "$API")" == "$EXPECTED" ]] || die "unexpected preview image"
[[ "$(docker inspect -f '{{.State.Running}}' "$API")" == true ]] || die "private preview not running"
[[ "$(stat -c '%a' "$DIR/owner-local.env")" == 600 ]] || die "private owner bootstrap missing or insecure"
[[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-backend)" == healthy ]] || die "live backend unhealthy"
[[ "$(docker inspect -f '{{.State.Health.Status}}' davarna-mysql)" == healthy ]] || die "live mysql unhealthy"

echo "===== CHECK NEW DB / OWNER / PAYMENT SAFETY ====="
docker exec -i "$API" python - <<'PY'
from app.core import config as c
from app.core.db import SessionLocal
from app.models.user import User
from app.models.rbac import Role, UserRole
from app.models.wallet import Wallet, WalletTx
from app.models.crypto import CryptoDepositRequest
from app.models.finance import DepositRequest, WithdrawRequest
from app.services.crypto_deposit_service import CryptoDepositService
from sqlalchemy import select, func
from sqlalchemy.engine import make_url
url=make_url(c.DATABASE_URL)
assert url.database=="davarna_zero_20261110" and url.host=="davarna-zero-mysql-20261110"
assert not c.CRYPTO_PAYMENTS_ENABLED and not c.CRYPTO_AUTO_CONFIRM_ENABLED
assert not c.GAME_AUTO_DRAW_ENABLED and not c.GAME_AUTOPILOT_RUNTIME_ENABLED
with SessionLocal() as db:
    assert db.execute(select(func.count()).select_from(User)).scalar_one()==1
    assert db.execute(select(func.count()).select_from(UserRole)).scalar_one()==1
    role=db.execute(select(Role.name).join(UserRole,Role.id==UserRole.role_id).where(UserRole.user_id==1)).scalar_one()
    assert role=="SUPER_ADMIN"
    for model in (Wallet,WalletTx,CryptoDepositRequest,DepositRequest,WithdrawRequest):
        assert db.execute(select(func.count()).select_from(model)).scalar_one()==0, model.__tablename__
    assert not CryptoDepositService.runtime_enabled(db)
print("PASS: new owner exists, financial data empty, payments disabled")
PY

# Existing destination values are only compared in RAM and never printed.
mapfile -t OLD_DESTS < <(docker exec davarna-backend python -c 'from app.core import config as c; print(c.CRYPTO_TRON_USDT_ADDRESS);print(c.CRYPTO_TON_ADDRESS)')
[[ "${#OLD_DESTS[@]}" == 2 ]] || die "could not verify current live destination addresses"

echo "===== ENTER NEW PUBLIC RECEIVE ADDRESSES ONLY ====="
echo "Never enter a seed phrase, recovery phrase, private key, API key or mnemonic."
read -r -p "NEW TRON USDT (TRC20) receive address (starts T): " NEW_TRON
read -r -p "NEW TON native receive address (TON network): " NEW_TON
[[ -n "$NEW_TRON" && -n "$NEW_TON" ]] || die "both addresses required"
[[ "$NEW_TRON" != "${OLD_DESTS[0]}" ]] || die "TRON address must differ from existing live address"
[[ "$NEW_TON" != "${OLD_DESTS[1]}" ]] || die "TON address must differ from existing live address"

echo "===== VALIDATE CHECKSUMS USING EXACT CANDIDATE CODE ====="
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  -e "NEW_TRON=$NEW_TRON" -e "NEW_TON=$NEW_TON" \
  --entrypoint python "$IMAGE" -c '
import os
from app.services.crypto_address_change import validate_crypto_destination
for chain, name in (("TRON","NEW_TRON"),("TON","NEW_TON")):
    value=os.environ[name]
    assert validate_crypto_destination(chain,value)==value
    print(f"PASS: {chain} receive address format and checksum")
'

# Atomic local-only staging. Never write old .env.prod or new DB at this step.
TMP="$(mktemp "$DIR/.addresses.XXXXXX")"
trap 'rm -f -- "$TMP"' EXIT
printf 'CRYPTO_TRON_USDT_ADDRESS=%s\nCRYPTO_TON_ADDRESS=%s\nCRYPTO_TRON_USDT_ENABLED=true\nCRYPTO_TON_ENABLED=true\nCRYPTO_PAYMENTS_ENABLED=false\nCRYPTO_AUTO_CONFIRM_ENABLED=false\nCRYPTO_DIRECT_WALLET_PAYMENTS_ENABLED=false\nDAVARNA_CRYPTO_ROTATION_PRODUCTION=\nDAVARNA_CRYPTO_ROTATION_EXPERIMENTAL=\n' \
  "$NEW_TRON" "$NEW_TON" > "$TMP"
chmod 0600 "$TMP"
[[ ! -e "$DEST" ]] || die "destination appeared during staging"
mv -n -- "$TMP" "$DEST"
trap - EXIT
[[ -s "$DEST" && "$(stat -c '%a' "$DEST")" == 600 ]] || die "staging file verification failed"

echo "===== ZERO-KM RECEIVE ADDRESS STAGING PASS ====="
echo "TRON_VALIDATED=true"
echo "TON_VALIDATED=true"
echo "STAGED_FILE=$DEST (private: never paste or upload)"
echo "ACTIVE_ADDRESSES_CHANGED=false"
echo "NEW_DATABASE_CHANGED=false"
echo "PAYMENTS_ENABLED=false"
echo "OLD_PRODUCTION_UNCHANGED=true"
echo "NEXT=prepare verified cutover config, owner auth and frozen issuer checks"
