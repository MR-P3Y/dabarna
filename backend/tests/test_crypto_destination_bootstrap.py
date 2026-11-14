import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models.settings import AppSetting
from app.models.user import User
from app.services import crypto_destination_bootstrap as boot
from app.services.crypto_deposit_service import CRYPTO_RUNTIME_SETTING_KEY
from app.services.crypto_destination_state import state_key


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        User.__table__.create(engine)
        AppSetting.__table__.create(engine)
        self.db = Session(engine)
        self.addCleanup(self.db.close)
        self.db.add_all([AppSetting(k=CRYPTO_RUNTIME_SETTING_KEY, v_json=True), User(id=1, tg_user_id=10)])
        self.db.commit()
        self.enterContext(patch.object(boot, "production_rotation_enabled",return_value=True))
        self.enterContext(patch.object(boot.cfg, "RBAC_OWNER_USER_ID", 1))
        self.enterContext(patch("app.services.crypto_destination_state.rotation_enabled",return_value=True))
        self.enterContext(patch("app.services.crypto_deposit_service.rotation_enabled",return_value=True))
        self.enterContext(patch.multiple(boot.cfg, CRYPTO_TON_ENABLED=True, CRYPTO_TRON_USDT_ENABLED=True,
                                         CRYPTO_PAYMENTS_ENABLED=True))
        self.options = [{"network":"TON", "address":"0:" + "12"*32},
                        {"network":"TRON", "address":"TJRabPrwbZy45sbavfcjinPJC18kjpRTv8"}]
        self.enterContext(patch.object(boot.CryptoDepositService,"configured_options",return_value=self.options))

    def test_same_destinations_and_runtime_survive_retry(self):
        with self.db.begin():
            self.assertTrue(boot.prepare_existing_destinations(self.db)["issuance_enabled"])
        with self.db.begin():
            self.assertTrue(boot.prepare_existing_destinations(self.db)["addresses_preserved"])
        self.assertIs(self.db.get(AppSetting,CRYPTO_RUNTIME_SETTING_KEY).v_json, True)

    def test_second_network_failure_rolls_back_first_and_freeze(self):
        self.options[1]["address"]="malformed"
        with self.assertRaises(ValueError), self.db.begin():
            boot.prepare_existing_destinations(self.db)
        self.assertIsNone(self.db.get(AppSetting,state_key("TON")))
        self.assertIs(self.db.get(AppSetting,CRYPTO_RUNTIME_SETTING_KEY).v_json, True)
