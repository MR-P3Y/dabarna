"""Isolated SQLite contracts for crypto destination preview/draft/cancel (#30).

No live crypto addresses, network calls, wallet writes or Production DB.
"""
import base64
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import BigInteger, create_engine, func, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.crypto import CryptoDepositRequest
from app.models.crypto_destination_version import CryptoDestinationVersion
from app.services.crypto_address_rotation_validation import _crc16_xmodem
from app.services.crypto_destination_draft_service import CryptoDestinationDraftService


@compiles(BigInteger, "sqlite")
def _sqlite_bigint_as_integer(element, compiler, **kw):
    # SQLite autoincrement requires the exact INTEGER PRIMARY KEY name.
    return "INTEGER"


def _ton(seed: int, tag: int = 0x11) -> str:
    body = bytes([tag, 0]) + bytes([seed]) * 32
    return base64.urlsafe_b64encode(body + _crc16_xmodem(body)).decode().rstrip("=")


class CryptoDestinationDraftTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        User.__table__.create(self.engine)
        CryptoDepositRequest.__table__.create(self.engine)
        CryptoDestinationVersion.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.db.add(User(id=91001, tg_user_id=91001))
        self.db.commit()
        self.old, self.new, self.next = _ton(1), _ton(2), _ton(3)
        self.patch_config = patch(
            "app.services.crypto_destination_draft_service.cfg.CRYPTO_TON_ADDRESS", self.old,
        )
        self.patch_config.start()
        self.addCleanup(self.patch_config.stop)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _preview(self, address=None, expected_version=0):
        return CryptoDestinationDraftService.preview(
            self.db, network="TON", address=address or self.new,
            expected_version=expected_version,
        )

    def _draft(self, *, operation_id="operation-12345678", address=None, expected_version=0):
        return CryptoDestinationDraftService.create_draft(
            self.db, network="TON", address=address or self.new,
            reason="rotate synthetic destination",
            expected_version=expected_version,
            operation_id=operation_id,
            actor_id=91001,
        )

    def test_preview_is_read_only_and_activation_disabled(self):
        result = self._preview()
        self.assertEqual(result["current_address"], self.old)
        self.assertEqual(result["new_address"], self.new)
        self.assertFalse(result["can_activate"])
        self.assertEqual(result["proposed_version"], 1)
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(CryptoDestinationVersion)), 0,
        )

    def test_raw_ton_same_wallet_is_rejected(self):
        raw = "0:" + bytes([1]) * 32
        with self.assertRaises(HTTPException):
            self._preview(address="0:" + (bytes([1]) * 32).hex())
        with self.assertRaises(HTTPException):
            self._preview(address=_ton(1, tag=0x51))

    def test_stale_version_rejected(self):
        with self.assertRaises(HTTPException) as err:
            self._preview(expected_version=10)
        self.assertEqual(err.exception.status_code, 409)

    def test_draft_idempotency_and_one_open_draft(self):
        row, replay, preview = self._draft()
        self.db.commit()
        self.assertFalse(replay)
        self.assertEqual(row.state, "DRAFT")
        self.assertEqual(row.version, 1)
        same, replayed, _ = self._draft()
        self.assertTrue(replayed)
        self.assertEqual(same.id, row.id)
        with self.assertRaises(HTTPException) as err:
            self._draft(operation_id="another-operation-123")
        self.assertEqual(err.exception.status_code, 409)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(CryptoDestinationVersion)), 1)

    def test_cancel_maintains_history_and_new_version(self):
        row, _, _ = self._draft()
        self.db.commit()
        cancelled, replay = CryptoDestinationDraftService.cancel_draft(self.db, draft_id=row.id)
        self.assertFalse(replay)
        self.db.commit()
        _, replayed = CryptoDestinationDraftService.cancel_draft(self.db, draft_id=row.id)
        self.assertTrue(replayed)
        next_row, _, _ = self._draft(
            operation_id="another-operation-123", address=self.next, expected_version=1,
        )
        self.db.commit()
        self.assertEqual(next_row.version, 2)
        items = CryptoDestinationDraftService.versions(self.db, network="TON")
        self.assertEqual([x["state"] for x in items], ["DRAFT", "CANCELLED"])
        self.assertEqual([x["version"] for x in items], [2, 1])
        self.assertNotIn(self.old, str(items))
        self.assertNotIn(self.new, str(items))
        self.assertNotIn(self.next, str(items))

    def test_open_invoices_are_reported_and_not_modified(self):
        invoice = CryptoDepositRequest(
            public_id="synthetic-invoice-1",
            user_id=91001,
            active_user_id=91001,
            network="TON",
            asset="TON",
            amount_toman=50000,
            rate_toman_per_asset=Decimal("100000"),
            amount_crypto=Decimal("0.5"),
            rate_provider="synthetic",
            destination_address=self.old,
            status="WAITING_PAYMENT",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        self.db.add(invoice)
        self.db.commit()
        original_id = invoice.id
        before = invoice.destination_address
        snapshot = self._preview()
        self.assertEqual(snapshot["open_invoice_count"], 1)
        self.assertTrue(snapshot["open_destination_masks"])
        self.assertEqual(invoice.destination_address, before)
        self.assertEqual(invoice.id, original_id)

    def test_routes_require_super_admin(self):
        from app.routers.mini_router import router, get_mini_super_admin_identity
        paths = {
            "/mini-api/admin/super/crypto-destinations/versions",
            "/mini-api/admin/super/crypto-destinations/preview",
            "/mini-api/admin/super/crypto-destinations/drafts",
            "/mini-api/admin/super/crypto-destinations/drafts/{draft_id}/cancel",
        }
        for item in router.routes:
            if getattr(item, "path", None) in paths:
                self.assertIn(
                    get_mini_super_admin_identity,
                    [dep.call for dep in item.dependant.dependencies],
                    item.path,
                )
                paths.remove(item.path)
        self.assertFalse(paths, "Missing owner-protected routes")


if __name__ == "__main__":
    unittest.main()
