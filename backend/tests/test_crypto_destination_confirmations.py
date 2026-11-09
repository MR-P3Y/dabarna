"""No-network, no-Production tests for one-time human crypto review confirmation."""
from __future__ import annotations

import base64
import hashlib
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.crypto import CryptoDepositRequest
from app.models.crypto_destination_version import CryptoDestinationVersion
from app.models.crypto_destination_challenge import CryptoDestinationChallenge
from app.services.crypto_address_rotation_validation import _crc16_xmodem
from app.services.crypto_destination_draft_service import CryptoDestinationDraftService
from app.services.crypto_destination_confirmation_service import (
    CryptoDestinationConfirmationService,
)


@compiles(BigInteger, "sqlite")
def _sqlite_bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


def _ton(seed: int) -> str:
    body = bytes([0x11, 0]) + bytes([seed]) * 32
    return base64.urlsafe_b64encode(body + _crc16_xmodem(body)).decode().rstrip("=")


class CryptoConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        User.__table__.create(self.engine)
        CryptoDepositRequest.__table__.create(self.engine)
        CryptoDestinationVersion.__table__.create(self.engine)
        CryptoDestinationChallenge.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.db.add(User(id=91001, tg_user_id=91001))
        self.db.add(User(id=91002, tg_user_id=91002))
        self.db.commit()
        self.old, self.new, self.other = _ton(1), _ton(2), _ton(3)
        self.config_patch = patch(
            "app.services.crypto_destination_draft_service.cfg.CRYPTO_TON_ADDRESS", self.old,
        )
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.draft, _, _ = CryptoDestinationDraftService.create_draft(
            self.db, network="TON", address=self.new,
            expected_version=0, reason="synthetic confirmation review",
            operation_id="confirm-operation-001", actor_id=91001,
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def prepare(self):
        return CryptoDestinationConfirmationService.prepare(
            self.db, draft_id=self.draft.id, actor_id=91001,
        )

    def confirm(self, challenge, token, *, address=None, actor=91001):
        return CryptoDestinationConfirmationService.confirm(
            self.db, draft_id=self.draft.id, challenge_id=challenge.id,
            token=token, confirmed_address=address or self.new, actor_id=actor,
        )

    def test_prepare_is_bound_to_original_address_and_secret_is_hashed(self):
        challenge, token, draft = self.prepare()
        self.db.commit()
        self.assertEqual(draft.previous_address, self.old)
        self.assertEqual(draft.address, self.new)
        self.assertNotEqual(challenge.secret_digest, token)
        self.assertEqual(challenge.secret_digest, hashlib.sha256(token.encode("ascii")).hexdigest())
        self.assertEqual(draft.state, "DRAFT")

    def test_prepare_does_not_issue_parallel_valid_challenges(self):
        self.prepare()
        self.db.commit()
        with self.assertRaises(HTTPException) as err:
            self.prepare()
        self.assertEqual(err.exception.status_code, 409)

    def test_wrong_address_and_secret_fail_without_consumption(self):
        challenge, token, _ = self.prepare()
        self.db.commit()
        with self.assertRaises(HTTPException) as err:
            self.confirm(challenge, token, address=self.other)
        self.assertEqual(err.exception.status_code, 400)
        with self.assertRaises(HTTPException) as err:
            self.confirm(challenge, "not-the-token")
        self.assertEqual(err.exception.status_code, 403)
        self.db.refresh(challenge)
        self.assertIsNone(challenge.consumed_at)

    def test_valid_confirmation_is_single_use_and_cannot_activate(self):
        challenge, token, _ = self.prepare()
        self.db.commit()
        confirmed, row = self.confirm(challenge, token)
        self.db.commit()
        self.assertIsNotNone(confirmed.consumed_at)
        self.assertEqual(row.state, "DRAFT")
        self.assertEqual(row.previous_address, self.old)
        with self.assertRaises(HTTPException) as err:
            self.confirm(challenge, token)
        self.assertEqual(err.exception.status_code, 409)
        with self.assertRaises(HTTPException):
            self.prepare()

    def test_expired_challenge_is_not_accepted(self):
        challenge, token, _ = self.prepare()
        challenge.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        self.db.commit()
        with self.assertRaises(HTTPException) as err:
            self.confirm(challenge, token)
        self.assertEqual(err.exception.status_code, 409)
        newer, _, _ = self.prepare()
        self.db.commit()
        self.assertNotEqual(newer.id, challenge.id)

    def test_another_actor_cannot_prepare_or_confirm(self):
        with self.assertRaises(HTTPException) as err:
            CryptoDestinationConfirmationService.prepare(self.db, draft_id=self.draft.id, actor_id=91002)
        self.assertEqual(err.exception.status_code, 403)
        challenge, token, _ = self.prepare()
        self.db.commit()
        with self.assertRaises(HTTPException) as err:
            self.confirm(challenge, token, actor=91002)
        self.assertEqual(err.exception.status_code, 403)

    def test_config_drift_fails_closed(self):
        challenge, token, _ = self.prepare()
        self.db.commit()
        with patch(
            "app.services.crypto_destination_draft_service.cfg.CRYPTO_TON_ADDRESS", self.other,
        ):
            with self.assertRaises(HTTPException) as err:
                self.confirm(challenge, token)
            self.assertEqual(err.exception.status_code, 409)
        self.db.refresh(challenge)
        self.assertIsNone(challenge.consumed_at)

    def test_cancelled_draft_cannot_confirm(self):
        challenge, token, _ = self.prepare()
        self.db.commit()
        CryptoDestinationDraftService.cancel_draft(self.db, draft_id=self.draft.id)
        self.db.commit()
        with self.assertRaises(HTTPException) as err:
            self.confirm(challenge, token)
        self.assertEqual(err.exception.status_code, 409)

    def test_new_routes_use_owner_only_dependency(self):
        from app.routers.mini_router import router, get_mini_super_admin_identity
        paths = {
            "/mini-api/admin/super/crypto-destinations/drafts/{draft_id}/prepare-confirmation",
            "/mini-api/admin/super/crypto-destinations/drafts/{draft_id}/confirm",
        }
        for item in router.routes:
            if getattr(item, "path", None) in paths:
                self.assertIn(
                    get_mini_super_admin_identity,
                    [dependency.call for dependency in item.dependant.dependencies],
                )
                paths.discard(item.path)
        self.assertFalse(paths)


if __name__ == "__main__":
    unittest.main()
