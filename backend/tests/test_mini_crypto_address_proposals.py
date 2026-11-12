"""Security contract for staged wallet address proposals (SQLite, no production)."""
import hashlib
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, Base
from app.models.settings import AppSetting
from app.routers import mini_router as mini
from app.services.crypto_address_change import validate_crypto_destination


def tron_address(seed: int) -> str:
    raw = bytes([0x41]) + bytes([seed]) * 20
    data = raw + hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = int.from_bytes(data, "big")
    out = ""
    while number:
        number, n = divmod(number, 58)
        out = alphabet[n] + out
    return out


class CryptoAddressProposalTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        AppSetting.__table__.create(self.engine)
        self.old = tron_address(1)
        self.new = tron_address(2)
        self.app = FastAPI()
        self.app.include_router(mini.router)

        def session_dependency():
            with Session(self.engine) as db:
                yield db

        self.app.dependency_overrides[get_db] = session_dependency
        self.app.dependency_overrides[mini.get_mini_admin_identity] = lambda: mini.MiniAdminIdentity(
            user_id=101, tg_user_id=9101, roles=["SUPER_ADMIN"]
        )
        self.owner = patch.object(mini, "RBAC_OWNER_USER_ID", 101)
        self.options = patch.object(
            mini.CryptoDepositService, "configured_options",
            return_value=[{"network": "TRON", "address": self.old, "asset": "USDT"}],
        )
        self.audit = patch.object(mini.AdminAuditService, "record")
        self.limiter = patch.object(mini, "enforce_write_rate_limit")
        self.owner.start()
        self.options.start()
        self.audit.start()
        self.limiter.start()
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.audit.stop()
        self.limiter.stop()
        self.options.stop()
        self.owner.stop()
        self.engine.dispose()

    def request(self, address=None, expected=None):
        return self.client.post(
            "/mini-api/admin/super/crypto-address-proposals",
            json={
                "network": "TRON",
                "address": address or self.new,
                "expected_current_address": expected or self.old,
                "confirmation": "REQUEST_ADDRESS_CHANGE",
            },
        )

    def test_valid_checksum(self):
        self.assertEqual(validate_crypto_destination("TRON", self.new), self.new)
        with self.assertRaises(ValueError):
            validate_crypto_destination("TRON", self.new[:-1] + "0")
        self.assertEqual(validate_crypto_destination("TON", "0:" + "a" * 64), "0:" + "a" * 64)

    def test_proposal_is_pending_and_never_changes_active_settings(self):
        response = self.request()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertFalse(response.json()["activation_supported"])
        self.assertEqual(response.json()["status"], "PENDING_REVIEW")
        with Session(self.engine) as db:
            row = db.get(AppSetting, "crypto_address_change_proposal:TRON")
            self.assertEqual(row.v_json["address"], self.new)
        self.assertEqual(mini.CryptoDepositService.configured_options()[0]["address"], self.old)
        pending = self.client.get("/mini-api/admin/super/crypto-address-proposals")
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(len(pending.json()["items"]), 1)

    def test_duplicate_proposal_refused(self):
        self.assertEqual(self.request().status_code, 201)
        self.assertEqual(self.request().status_code, 409)

    def test_cancel_is_version_bound_and_changes_only_pending_proposal(self):
        self.assertEqual(self.request().status_code, 201)
        item = self.client.get("/mini-api/admin/super/crypto-address-proposals").json()["items"][0]
        body = {"network": "TRON", "expected_address": item["address"],
                "expected_created_at": item["created_at"], "confirmation": "CANCEL_PENDING_CRYPTO_ADDRESS"}
        url = "/mini-api/admin/super/crypto-address-proposals/cancel"
        self.assertEqual(self.client.post(url, json={**body, "expected_created_at": "stale"}).status_code, 409)
        response = self.client.post(url, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "CANCELLED")
        self.assertFalse(response.json()["activation"])
        with Session(self.engine) as db:
            rows = db.scalars(select(AppSetting)).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].v_json["status"], "CANCELLED")
        self.assertEqual(self.client.post(url, json=body).status_code, 409)
        self.assertEqual(self.request().status_code, 201)
        self.assertEqual(self.client.post(url, json=body).status_code, 409, "old cancellation must not cancel replacement")
        self.assertEqual(mini.CryptoDepositService.configured_options()[0]["address"], self.old)

    def test_cancel_is_owner_only(self):
        self.assertEqual(self.request().status_code, 201)
        item = self.client.get("/mini-api/admin/super/crypto-address-proposals").json()["items"][0]
        self.app.dependency_overrides[mini.get_mini_admin_identity] = lambda: mini.MiniAdminIdentity(
            user_id=202, tg_user_id=9202, roles=["ADMIN"])
        response = self.client.post("/mini-api/admin/super/crypto-address-proposals/cancel", json={
            "network": "TRON", "expected_address": item["address"],
            "expected_created_at": item["created_at"], "confirmation": "CANCEL_PENDING_CRYPTO_ADDRESS"})
        self.assertEqual(response.status_code, 403, response.text)

    def test_missing_owner_configuration_fails_closed(self):
        with patch.object(mini, "RBAC_OWNER_USER_ID", None):
            self.assertEqual(self.request().status_code, 503)
            response = self.client.get("/mini-api/admin/super/crypto-address-proposals")
            self.assertEqual(response.status_code, 503)
        with Session(self.engine) as db:
            self.assertEqual(db.scalars(select(AppSetting)).all(), [])

    def test_stale_current_address_refused(self):
        self.assertEqual(self.request(expected=self.new).status_code, 409)

    def test_invalid_checksum_refused(self):
        self.assertEqual(self.request(address="T" + "0" * 33).status_code, 422)

    def test_readiness_endpoint_remains_owner_only_and_read_only(self):
        self.assertEqual(self.request().status_code, 201)
        with patch.object(mini, "assess_rotation", return_value={
            "network": "TRON", "open_invoices": 1,
            "recent_closed_invoices": 2, "needs_manual_review": 3,
            "active_change_allowed": False,
        }) as assessment:
            response = self.client.get("/mini-api/admin/super/crypto-address-readiness?network=TRON")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(response.json()["active_change_allowed"])
            self.assertEqual(response.json()["recent_closed_invoices"], 2)
            assessment.assert_called_once()
        self.app.dependency_overrides[mini.get_mini_admin_identity] = lambda: mini.MiniAdminIdentity(
            user_id=202, tg_user_id=9202, roles=["ADMIN"]
        )
        denied = self.client.get("/mini-api/admin/super/crypto-address-readiness?network=TRON")
        self.assertEqual(denied.status_code, 403)

    def test_experimental_second_rotation_uses_persisted_active_destination(self):
        # The environment address remains OLD, but the versioned DB state
        # has moved to NEW. A subsequent proposal must target NEW.
        third = tron_address(3)
        with (
            patch.object(mini, "rotation_enabled", return_value=True),
            patch.object(mini.CryptoDepositService, "runtime_status", return_value={
                "options": [{"network": "TRON", "address": self.new}],
            }),
        ):
            stale = self.request(address=third, expected=self.old)
            self.assertEqual(stale.status_code, 409, stale.text)
            fresh = self.request(address=third, expected=self.new)
            self.assertEqual(fresh.status_code, 201, fresh.text)
        with Session(self.engine) as db:
            row = db.get(AppSetting, "crypto_address_change_proposal:TRON")
            self.assertEqual(row.v_json["address"], third)
            self.assertEqual(
                row.v_json["previous_address_sha256"],
                hashlib.sha256(self.new.encode()).hexdigest(),
            )

    def test_experimental_readiness_uses_versioned_destination(self):
        with (
            patch.object(mini, "rotation_enabled", return_value=True),
            patch.object(mini.CryptoDepositService, "runtime_status", return_value={
                "options": [{"network": "TRON", "address": self.new}],
            }),
        ):
            self.assertEqual(self.request(address=tron_address(3), expected=self.new).status_code, 201)
            with patch.object(mini, "assess_rotation", return_value={
                "active_change_allowed": False,
                "open_invoices": 0,
                "recent_closed_invoices": 0,
                "needs_manual_review": 0,
            }) as assessment:
                response = self.client.get(
                    "/mini-api/admin/super/crypto-address-readiness?network=TRON"
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(assessment.call_args.kwargs["current_address"], self.new)

    def test_experimental_proposal_listing_includes_current_version(self):
        self.assertEqual(self.request().status_code, 201)
        with (
            patch.object(mini, "rotation_enabled", return_value=True),
            patch.object(mini, "disposable_rotation_enabled", return_value=True),
            patch.object(mini.CryptoDepositService, "runtime_status", return_value={
                "options": [{
                    "network": "TRON", "address": self.new, "destination_version": 2,
                }],
            }),
        ):
            response = self.client.get("/mini-api/admin/super/crypto-address-proposals")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["activation_supported"])
        self.assertEqual(body["items"][0]["expected_version"], 2)
        self.assertEqual(body["items"][0]["expected_current_address"], self.new)

    def test_production_proposal_listing_exposes_no_activation_version(self):
        self.assertEqual(self.request().status_code, 201)
        with patch.object(mini, "rotation_enabled", return_value=False):
            response = self.client.get("/mini-api/admin/super/crypto-address-proposals")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["activation_supported"])
        self.assertNotIn("expected_version", body["items"][0])

    def test_production_proposal_still_uses_environment_destination(self):
        # Even if a stale experimental record exists, the real environment
        # address is authoritative when disposable rotation mode is off.
        with patch.object(mini, "rotation_enabled", return_value=False):
            self.assertEqual(self.request().status_code, 201)

    def test_production_endpoint_closed_without_strong_environment_gate(self):
        response = self.client.post(
            "/mini-api/admin/super/crypto-address-activate-production",
            json={
                "network": "TRON", "expected_version": 1,
                "expected_current_address": self.old,
                "proposed_address": self.new,
                "confirmation": "ACTIVATE_PRODUCTION_CRYPTO_DESTINATION",
            },
        )
        self.assertEqual(response.status_code, 409)

    def test_production_bootstrap_requires_explicit_paused_runtime_record(self):
        with patch.object(mini, "production_rotation_enabled", return_value=True):
            response = self.client.post(
                "/mini-api/admin/super/crypto-address-prepare-production",
                json={
                    "network": "TRON", "expected_current_address": self.old,
                    "confirmation": "PREPARE_PRODUCTION_CRYPTO_DESTINATION",
                },
            )
            self.assertEqual(response.status_code, 409, response.text)
        with Session(self.engine) as db:
            db.add(AppSetting(k="crypto_payments_runtime_enabled", v_json=True))
            db.commit()
        with patch.object(mini, "production_rotation_enabled", return_value=True):
            response = self.client.post(
                "/mini-api/admin/super/crypto-address-prepare-production",
                json={
                    "network": "TRON", "expected_current_address": self.old,
                    "confirmation": "PREPARE_PRODUCTION_CRYPTO_DESTINATION",
                },
            )
            self.assertEqual(response.status_code, 409, response.text)

    def test_production_activation_refuses_historical_invoices(self):
        self.assertEqual(self.request().status_code, 201)
        with Session(self.engine) as db:
            db.add(AppSetting(k="crypto_payments_runtime_enabled", v_json=False))
            db.commit()
        with (
            patch.object(mini, "production_rotation_enabled", return_value=True),
            patch.object(mini, "lock_destination_state",
                         return_value={"network": "TRON", "version": 1, "address": self.old}),
            patch.object(mini, "assess_rotation", return_value={
                "open_invoices": 0, "recent_closed_invoices": 0,
                "needs_manual_review": 0, "historical_invoices": 20,
            }),
            patch.object(mini, "rotate_locked") as rotate,
        ):
            response = self.client.post(
                "/mini-api/admin/super/crypto-address-activate-production",
                json={
                    "network": "TRON", "expected_version": 1,
                    "expected_current_address": self.old,
                    "proposed_address": self.new,
                    "confirmation": "ACTIVATE_PRODUCTION_CRYPTO_DESTINATION",
                },
            )
        self.assertEqual(response.status_code, 409, response.text)
        rotate.assert_not_called()

    def test_production_activation_refuses_stale_version_before_write(self):
        self.assertEqual(self.request().status_code, 201)
        with Session(self.engine) as db:
            db.add(AppSetting(k="crypto_payments_runtime_enabled", v_json=False))
            db.commit()
        with (
            patch.object(mini, "production_rotation_enabled", return_value=True),
            patch.object(mini, "lock_destination_state",
                         return_value={"network": "TRON", "version": 2, "address": self.old}),
            patch.object(mini, "rotate_locked") as rotate,
        ):
            response = self.client.post(
                "/mini-api/admin/super/crypto-address-activate-production",
                json={
                    "network": "TRON", "expected_version": 1,
                    "expected_current_address": self.old,
                    "proposed_address": self.new,
                    "confirmation": "ACTIVATE_PRODUCTION_CRYPTO_DESTINATION",
                },
            )
        self.assertEqual(response.status_code, 409, response.text)
        rotate.assert_not_called()

    def test_production_activation_commits_audited_version_but_does_not_enable_deposits(self):
        self.assertEqual(self.request().status_code, 201)
        with Session(self.engine) as db:
            db.add(AppSetting(k="crypto_payments_runtime_enabled", v_json=False))
            db.commit()
        with (
            patch.object(mini, "production_rotation_enabled", return_value=True),
            patch.object(mini, "lock_destination_state",
                         return_value={"network": "TRON", "version": 1, "address": self.old}),
            patch.object(mini, "assess_rotation", return_value={
                "open_invoices": 0, "recent_closed_invoices": 0,
                "needs_manual_review": 0, "historical_invoices": 0,
            }),
            patch.object(mini.CryptoChainService, "list_incoming", return_value=[]),
            patch.object(mini, "rotate_locked", return_value={
                "network": "TRON", "address": self.new, "version": 2,
            }) as rotate,
        ):
            response = self.client.post(
                "/mini-api/admin/super/crypto-address-activate-production",
                json={
                    "network": "TRON", "expected_version": 1,
                    "expected_current_address": self.old,
                    "proposed_address": self.new,
                    "confirmation": "ACTIVATE_PRODUCTION_CRYPTO_DESTINATION",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["production_activation"])
        self.assertFalse(response.json()["runtime_enabled"])
        rotate.assert_called_once()
        with Session(self.engine) as db:
            row = db.get(AppSetting, "crypto_address_change_proposal:TRON")
            self.assertEqual(row.v_json["status"], "ACTIVATED_PRODUCTION")
            self.assertEqual(row.v_json["activated_version"], 2)
            self.assertIs(db.get(AppSetting, "crypto_payments_runtime_enabled").v_json, False)

    def test_production_preflight_failure_never_rotates_destination(self):
        self.assertEqual(self.request().status_code, 201)
        with Session(self.engine) as db:
            db.add(AppSetting(k="crypto_payments_runtime_enabled", v_json=False))
            db.commit()
        with (
            patch.object(mini, "production_rotation_enabled", return_value=True),
            patch.object(mini, "lock_destination_state",
                         return_value={"network": "TRON", "version": 1, "address": self.old}),
            patch.object(mini, "assess_rotation", return_value={
                "open_invoices": 0, "recent_closed_invoices": 0,
                "needs_manual_review": 0, "historical_invoices": 0,
            }),
            patch.object(mini.CryptoChainService, "list_incoming",
                         side_effect=RuntimeError("provider unavailable")),
            patch.object(mini, "rotate_locked") as rotate,
        ):
            response = self.client.post(
                "/mini-api/admin/super/crypto-address-activate-production",
                json={
                    "network": "TRON", "expected_version": 1,
                    "expected_current_address": self.old,
                    "proposed_address": self.new,
                    "confirmation": "ACTIVATE_PRODUCTION_CRYPTO_DESTINATION",
                },
            )
        self.assertEqual(response.status_code, 503, response.text)
        rotate.assert_not_called()
        with Session(self.engine) as db:
            proposal = db.get(AppSetting, "crypto_address_change_proposal:TRON")
            self.assertEqual(proposal.v_json["status"], "PENDING_REVIEW")

    def test_non_superadmin_denied(self):
        self.app.dependency_overrides[mini.get_mini_admin_identity] = lambda: mini.MiniAdminIdentity(
            user_id=202, tg_user_id=9202, roles=["ADMIN"]
        )
        self.assertEqual(self.request().status_code, 403)
        self.assertEqual(
            self.client.get("/mini-api/admin/super/crypto-address-proposals").status_code, 403
        )


if __name__ == "__main__":
    unittest.main()
