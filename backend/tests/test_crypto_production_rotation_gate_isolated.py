"""Production wallet rotation opt-in must fail closed by default."""
import unittest
from unittest.mock import patch

from app.services.crypto_destination_state import (
    production_rotation_enabled, disposable_rotation_enabled, rotation_enabled,
    PRODUCTION_APPROVAL,
)


class ProductionRotationGateTests(unittest.TestCase):
    def test_default_is_off_on_real_database(self):
        with patch.dict("os.environ", {
            "DATABASE_URL": "mysql+pymysql://x:y@mysql/davarna",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION_DB": "davarna",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION": "",
            "DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL": "",
        }):
            self.assertFalse(rotation_enabled())

    def test_requires_exact_database_and_approval(self):
        with patch.dict("os.environ", {
            "DATABASE_URL": "mysql+pymysql://x:y@mysql/davarna",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION_DB": "another_db",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION": PRODUCTION_APPROVAL,
            "DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL": "",
        }):
            self.assertFalse(production_rotation_enabled())
        with patch.dict("os.environ", {
            "DATABASE_URL": "mysql+pymysql://x:y@mysql/davarna",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION_DB": "davarna",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION": PRODUCTION_APPROVAL,
            "DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL": "",
        }):
            self.assertTrue(production_rotation_enabled())
            self.assertTrue(rotation_enabled())
            self.assertFalse(disposable_rotation_enabled())

    def test_clean_launch_host_must_match_exact_allowlisted_host_and_schema(self):
        with patch.dict("os.environ", {
            "DATABASE_URL": "mysql+pymysql://x:y@davarna-zero-mysql-20261110/davarna_zero_20261110",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION_DB": "davarna_zero_20261110",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION_DB_HOST": "davarna-zero-mysql-20261110",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION": PRODUCTION_APPROVAL,
            "DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL": "",
        }):
            self.assertTrue(production_rotation_enabled())
        with patch.dict("os.environ", {
            "DATABASE_URL": "mysql+pymysql://x:y@mysql/PEYMOON_DAVARNA",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION_DB": "davarna_zero_20261110",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION_DB_HOST": "davarna-zero-mysql-20261110",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION": PRODUCTION_APPROVAL,
            "DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL": "",
        }):
            self.assertFalse(production_rotation_enabled())
        with patch.dict("os.environ", {
            "DATABASE_URL": "mysql+pymysql://x:y@attacker.example/davarna_zero_20261110",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION_DB": "davarna_zero_20261110",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION_DB_HOST": "attacker.example",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION": PRODUCTION_APPROVAL,
            "DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL": "",
        }):
            self.assertFalse(production_rotation_enabled())

    def test_experimental_gate_never_activates_production(self):
        with patch.dict("os.environ", {
            "DATABASE_URL": "mysql+pymysql://x:y@mysql/davarna",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION": "",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION_DB": "davarna",
            "DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL": "I_ACK_DISPOSABLE_DB_ONLY",
        }):
            self.assertFalse(rotation_enabled())
            self.assertFalse(disposable_rotation_enabled())

    def test_rejects_disposable_schema_as_production(self):
        with patch.dict("os.environ", {
            "DATABASE_URL": "mysql+pymysql://x:y@mysql/davarna_wallet_rotation_test",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION_DB": "davarna_wallet_rotation_test",
            "DAVARNA_CRYPTO_ROTATION_PRODUCTION": PRODUCTION_APPROVAL,
            "DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL": "",
        }):
            self.assertFalse(production_rotation_enabled())


if __name__ == "__main__":
    unittest.main()
