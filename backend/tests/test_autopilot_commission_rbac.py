from __future__ import annotations

import os
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.admin_guard import AdminIdentity, AdminScope, require_admin_any
from app.core.db import get_db
from app.routers import admin_autopilot_router, mini_router
from app.services.game_autopilot_config_service import GameAutopilotConfigService


def fake_config():
    return SimpleNamespace(
        level="LOW",
        enabled=0,
        scheduler_mode="MANUAL",
        start_mode="MANUAL",
        draw_mode="MANUAL",
        card_price=5000,
        game_rule="LINE",
        commission_rate=Decimal("0.1000"),
        announce_before_seconds=300,
        countdown_seconds=30,
        repeat_interval_seconds=600,
        draw_interval_seconds=8,
        cooldown_seconds=60,
        min_unique_players=2,
        updated_by=None,
        updated_at=None,
    )


class AutopilotCommissionRbacTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.row = fake_config()
        self.db.get.return_value = self.row
        self.admin = AdminIdentity(
            scope=AdminScope.ADMIN, token="fake-test-token", user_id=10,
            roles={"ADMIN"},
        )
        self.mini_admin = mini_router.MiniAdminIdentity(
            user_id=10, tg_user_id=500, roles=["ADMIN"],
        )
        self.app = FastAPI()
        self.app.include_router(admin_autopilot_router.router)
        self.app.include_router(mini_router.router)
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[require_admin_any] = lambda: self.admin
        self.app.dependency_overrides[mini_router.get_mini_admin_identity] = (
            lambda: self.mini_admin
        )
        p1 = patch.object(GameAutopilotConfigService, "list", return_value=[self.row])
        p2 = patch.object(admin_autopilot_router.AdminAuditService, "record")
        self.audit = p2.start()
        p1.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def status(self, path, code, payload=None):
        response = (
            self.client.get(path)
            if payload is None
            else self.client.put(path, json=payload)
        )
        self.assertEqual(response.status_code, code, response.text)
        return response

    def test_regular_admin_get_hides_commission_control(self):
        for path in (
            "/admin/autopilot/config",
            "/mini-api/admin/autopilot/config",
        ):
            with self.subTest(path=path):
                self.assertIs(
                    self.status(path, 200).json()["can_edit_commission"], False
                )

    def test_game_operator_get_hides_commission_control(self):
        self.admin = AdminIdentity(
            scope=AdminScope.ADMIN, token="fake-test-token", user_id=10,
            roles={"GAME_OPERATOR"},
        )
        self.mini_admin = mini_router.MiniAdminIdentity(
            user_id=10, tg_user_id=500, roles=["GAME_OPERATOR"],
        )
        for path in (
            "/admin/autopilot/config",
            "/mini-api/admin/autopilot/config",
        ):
            with self.subTest(path=path):
                self.assertIs(
                    self.status(path, 200).json()["can_edit_commission"], False
                )

    def test_regular_admin_cannot_change_commission(self):
        for path in (
            "/admin/autopilot/config/LOW",
            "/mini-api/admin/autopilot/config/LOW",
        ):
            with self.subTest(path=path):
                self.status(path, 403, {"commission_rate": 0.25})
                self.assertEqual(self.row.commission_rate, Decimal("0.1000"))
        self.db.flush.assert_not_called()
        self.db.commit.assert_not_called()
        self.audit.assert_not_called()

    def test_game_operator_cannot_change_commission(self):
        self.admin = AdminIdentity(
            scope=AdminScope.ADMIN, token="fake-test-token", user_id=10,
            roles={"GAME_OPERATOR"},
        )
        self.mini_admin = mini_router.MiniAdminIdentity(
            user_id=10, tg_user_id=500, roles=["GAME_OPERATOR"],
        )
        for path in (
            "/admin/autopilot/config/LOW",
            "/mini-api/admin/autopilot/config/LOW",
        ):
            with self.subTest(path=path):
                self.status(path, 403, {"commission_rate": 0.25})
        self.db.commit.assert_not_called()
        self.audit.assert_not_called()

    def test_super_admin_can_change_commission(self):
        self.admin = AdminIdentity(
            scope=AdminScope.SUPER_ADMIN, token="fake-test-token", user_id=11,
            roles={"SUPER_ADMIN"},
        )
        self.mini_admin = mini_router.MiniAdminIdentity(
            user_id=11, tg_user_id=501, roles=["SUPER_ADMIN"],
        )
        for path in (
            "/admin/autopilot/config",
            "/mini-api/admin/autopilot/config",
        ):
            self.assertIs(
                self.status(path, 200).json()["can_edit_commission"], True
            )
        for path in (
            "/admin/autopilot/config/LOW",
            "/mini-api/admin/autopilot/config/LOW",
        ):
            self.status(path, 200, {"commission_rate": 0.20})
            self.assertEqual(self.row.commission_rate, Decimal("0.2000"))
        self.assertEqual(self.db.commit.call_count, 2)
        self.assertEqual(self.audit.call_count, 2)

    def test_regular_admin_can_edit_nonfinancial_schedule(self):
        for path in (
            "/admin/autopilot/config/LOW",
            "/mini-api/admin/autopilot/config/LOW",
        ):
            self.status(path, 200, {"draw_interval_seconds": 10})
            self.assertEqual(self.row.draw_interval_seconds, 10)
        self.assertEqual(self.db.commit.call_count, 2)

    def test_player_threshold_is_saved_per_lane_and_survives_other_edits(self):
        for path in ("/admin/autopilot/config/LOW", "/mini-api/admin/autopilot/config/LOW"):
            for players in (1, 3):
                self.status(path, 200, {"min_unique_players": players})
                self.assertEqual(self.row.min_unique_players, players)
                self.status(path, 200, {"countdown_seconds": 35})
                self.assertEqual(self.row.min_unique_players, players)
            for value, status in ((0, 400), (-1, 400), (2147483648, 400),
                                  (True, 422), (1.5, 422), ("3", 422)):
                with self.subTest(path=path, value=value):
                    self.status(path, status, {"min_unique_players": value})
                    self.assertEqual(self.row.min_unique_players, 3)

    def test_admin_controls_countdown_with_bounds(self):
        for path in ('/admin/autopilot/config/LOW','/mini-api/admin/autopilot/config/LOW'):
            for seconds in (5,45,600):
                with self.subTest(path=path,seconds=seconds):
                    self.status(path,200,{'countdown_seconds':seconds})
                    self.assertEqual(self.row.countdown_seconds,seconds)
            for seconds in (4,601):
                before=self.db.commit.call_count
                self.status(path,400,{'countdown_seconds':seconds})
                self.assertEqual(self.db.commit.call_count,before)

    def test_fast_interval_permission_depends_on_rule(self):
        for path in ('/admin/autopilot/config/LOW','/mini-api/admin/autopilot/config/LOW'):
            for rule in ('LINE','FULL_CARD','LEGACY'):
                self.row.game_rule=rule
                for seconds in (2,3,4):
                    with self.subTest(path=path,rule=rule,seconds=seconds):
                        before=self.db.commit.call_count
                        self.status(path,200 if rule=='FULL_CARD' else 400,{'draw_interval_seconds':seconds})
                        if rule=='FULL_CARD':
                            self.assertEqual(self.row.draw_interval_seconds,seconds)
                        else:
                            self.assertEqual(self.db.commit.call_count,before)


if __name__ == "__main__":
    unittest.main()
