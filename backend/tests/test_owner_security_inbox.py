import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/15")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.routers import mini_router as mini


class OwnerSecurityInboxTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(engine.dispose)
        for model in (mini.User, mini.Wallet, mini.DepositRequest, mini.WithdrawRequest,
                      mini.CryptoDepositRequest, mini.AdminAuditLog):
            model.__table__.create(engine)
        self.db = Session(engine)
        self.addCleanup(self.db.close)
        for audit_id, operation in enumerate((
            "activate_production_crypto_destination", "propose_crypto_destination",
            "activate_experimental_crypto_destination",
        ), 1):
            self.db.add(mini.AdminAuditLog(
                id=audit_id, actor_user_id=7, actor_scope="SUPER_ADMIN",
                action="settings.update", target_type="app_setting",
                details_json={"operation": operation, "address": "private-test-value"},
            ))
        self.db.commit()

    def inbox(self, user_id, owner_id):
        with patch.object(mini, "RBAC_OWNER_USER_ID", owner_id):
            return mini.mini_my_notifications(limit=40, user_id=user_id, db=self.db)["items"]

    def test_only_committed_production_activation_has_stable_private_notice(self):
        items = self.inbox(7, 7)
        self.assertEqual([item["id"] for item in items], ["destination-change:1"])
        self.assertEqual(items[0]["route"]["section"], "audit")
        self.assertEqual(items[0]["severity"], "danger")
        self.assertEqual(items[0]["route"]["target_id"], 1)
        self.assertNotIn("private-test-value", json.dumps(items))
        self.assertEqual(self.inbox(7, 7), items)

    def test_other_accounts_and_unconfigured_owner_have_no_notice(self):
        self.assertEqual(self.inbox(8, 7), [])
        self.assertEqual(self.inbox(7, None), [])
