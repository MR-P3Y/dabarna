"""One-time release preparation while all application writers are stopped.

Seed exactly the existing server destinations. The operator cannot supply an
address. The caller owns a single transaction for both networks.
"""
from sqlalchemy import select
from app.core import config as cfg
from app.models.settings import AppSetting
from app.models.user import User
from app.services.crypto_deposit_service import CryptoDepositService, CRYPTO_RUNTIME_SETTING_KEY
from app.services.crypto_destination_state import (
    lock_destination_state, production_rotation_enabled, seed_destination_state, state_key,
)


def prepare_existing_destinations(db):
    if not production_rotation_enabled() or not cfg.RBAC_OWNER_USER_ID or not db.get(User, cfg.RBAC_OWNER_USER_ID):
        raise RuntimeError("Production database gate and configured owner required")
    options = {item["network"]: item["address"] for item in CryptoDepositService.configured_options()}
    if set(options) != {"TON", "TRON"}:
        raise RuntimeError("Both active network destinations are required")
    runtime = db.execute(select(AppSetting).where(
        AppSetting.k == CRYPTO_RUNTIME_SETTING_KEY).with_for_update()).scalar_one()
    previous = runtime.v_json
    # Writers are stopped. This temporary freeze is never committed separately.
    runtime.v_json = False
    db.flush()
    for network, address in sorted(options.items()):
        if db.get(AppSetting, state_key(network)) is None:
            seed_destination_state(db, network=network, address=address)
        record = lock_destination_state(db, network)
        if record["version"] != 1 or record["address"] != address:
            raise RuntimeError("Existing destination does not match initial server configuration")
    runtime.v_json = previous
    db.flush()
    effective = CryptoDepositService.runtime_status(db)
    if {r["network"]: r["address"] for r in effective["options"]} != options:
        raise RuntimeError("Effective invoice destinations differ")
    return {"networks": sorted(options), "versions": [1, 1], "addresses_preserved": True,
            "issuance_enabled": effective["enabled"]}
