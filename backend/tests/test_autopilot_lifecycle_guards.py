"""Isolated Autopilot lifecycle guard tests; no real DB, Redis, Telegram or money."""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import ExitStack

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")

from app.models.game_autopilot import GameAutopilotConfig
from app.services.game_autopilot_worker import GameAutopilotWorker


class AutopilotLifecycleGuardTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 6, 18, 0, 0)
        self.db = Mock()
        self.config = SimpleNamespace(
            enabled=1, scheduler_mode="AUTO", start_mode="AUTO",
            draw_mode="AUTO", card_price=5000, min_unique_players=2,
            countdown_seconds=30, draw_interval_seconds=8,
            cooldown_seconds=60, repeat_interval_seconds=120,
        )
        self.game = SimpleNamespace(
            id=9001, status="LOBBY", execution_source="SYSTEM",
            draw_mode="AUTO", draw_mode_locked_at=None,
            scheduled_start_at=None,
        )

    def manage(self, players, *, auto_draw=True):
        with (
            patch.object(GameAutopilotWorker, "_ensure_draw_mode") as ensure,
            patch.object(GameAutopilotWorker, "_unique_players", return_value=players) as count,
            patch("app.services.game_autopilot_worker.cfg.GAME_AUTO_DRAW_ENABLED", auto_draw),
            patch("app.services.game_autopilot_worker.GameService.start_game") as start,
        ):
            result = GameAutopilotWorker._manage_active(
                self.db, game=self.game, config=self.config,
                actor_user_id=42, now=self.now,
            )
            return result, ensure, count, start

    def execute_level(self, *, active=None, latest=None):
        with ExitStack() as stack:
            session = stack.enter_context(
                patch("app.services.game_autopilot_worker.SessionLocal")
            )
            active_game = stack.enter_context(
                patch.object(GameAutopilotWorker, "_active_game", return_value=active)
            )
            ended_game = stack.enter_context(
                patch.object(GameAutopilotWorker, "_latest_ended_game", return_value=latest)
            )
            create = stack.enter_context(
                patch("app.services.game_autopilot_worker.GameService.create_game")
            )
            ensure = stack.enter_context(
                patch.object(GameAutopilotWorker, "_ensure_draw_mode")
            )
            stack.enter_context(
                patch("app.services.game_autopilot_worker._utcnow_naive", return_value=self.now)
            )
            stack.enter_context(
                patch("app.services.game_autopilot_worker.cfg.GAME_AUTO_DRAW_ENABLED", True)
            )
            stack.enter_context(
                patch("app.services.game_autopilot_worker.cfg.USER_FORUM_CHAT_ID", -100900)
            )
            stack.enter_context(
                patch("app.services.game_autopilot_worker.cfg.GAME_AUTOPILOT_SYSTEM_USER_ID", 42)
            )
            stack.enter_context(
                patch(
                    "app.services.game_autopilot_worker.GameAutopilotConfigService.topic_id_for_level",
                    return_value=6,
                )
            )
            db = session.return_value.__enter__.return_value
            db.get.side_effect = (
                lambda cls, key: self.config
                if cls is GameAutopilotConfig
                else SimpleNamespace(id=42)
            )
            create.return_value = SimpleNamespace(
                id=9002, status="LOBBY", execution_source="SYSTEM",
                draw_mode="AUTO", draw_mode_locked_at=None,
            )
            state = GameAutopilotWorker._run_level("LOW")
            return state, db, create, ensure, active_game, ended_game

    def test_single_player_never_arms_countdown_or_starts(self):
        result, _, _, start = self.manage(1)
        self.assertEqual(result, "waiting_players")
        self.assertIsNone(self.game.scheduled_start_at)
        self.db.flush.assert_not_called()
        start.assert_not_called()

    def test_zero_players_never_starts(self):
        result, _, _, start = self.manage(0)
        self.assertEqual(result, "waiting_players")
        start.assert_not_called()

    def test_two_players_arm_countdown_without_starting(self):
        result, _, _, start = self.manage(2)
        self.assertEqual(result, "countdown_armed")
        self.assertEqual(
            self.game.scheduled_start_at,
            self.now + timedelta(seconds=30),
        )
        self.db.flush.assert_called_once()
        start.assert_not_called()

    def test_start_before_countdown_expires_is_blocked(self):
        self.game.scheduled_start_at = self.now + timedelta(seconds=10)
        result, _, _, start = self.manage(2)
        self.assertEqual(result, "countdown_wait")
        start.assert_not_called()

    def test_two_players_start_after_countdown_with_stable_idempotency_key(self):
        self.game.scheduled_start_at = self.now - timedelta(seconds=1)
        result, _, _, start = self.manage(2)
        self.assertEqual(result, "started")
        start.assert_called_once_with(
            db=self.db, game_id=9001, admin_user_id=42,
            idempotency_key="autopilot:start:9001",
            can_manage_any=True,
        )

    def test_auto_draw_disabled_blocks_auto_game_start(self):
        result, _, count, start = self.manage(2, auto_draw=False)
        self.assertEqual(result, "blocked_auto_draw_disabled")
        count.assert_not_called()
        start.assert_not_called()

    def test_manual_start_setting_never_starts_game(self):
        self.config.start_mode = "MANUAL"
        result, _, count, start = self.manage(2)
        self.assertEqual(result, "lobby_manual_start")
        count.assert_not_called()
        start.assert_not_called()

    def test_existing_manual_admin_game_blocks_lane(self):
        game = SimpleNamespace(execution_source="ADMIN", status="LOBBY")
        state, db, create, ensure, _, _ = self.execute_level(active=game)
        self.assertEqual(state, "blocked_manual_active")
        create.assert_not_called()
        ensure.assert_not_called()
        db.commit.assert_not_called()

    def test_cooldown_prevents_immediate_repeat(self):
        previous = SimpleNamespace(
            ended_at=self.now - timedelta(seconds=30),
            created_at=self.now - timedelta(seconds=300),
        )
        state, db, create, _, _, _ = self.execute_level(latest=previous)
        self.assertEqual(state, "cooldown")
        create.assert_not_called()
        db.commit.assert_not_called()

    def test_create_system_game_when_lane_empty_and_cooldown_elapsed(self):
        previous = SimpleNamespace(
            ended_at=self.now - timedelta(seconds=200),
            created_at=self.now - timedelta(seconds=300),
        )
        state, db, create, ensure, _, _ = self.execute_level(latest=previous)
        self.assertEqual(state, "created")
        create.assert_called_once_with(
            db=db, admin_user_id=42, tg_group_id=-100900,
            tg_topic_id=6, card_price=5000, game_level="LOW",
            execution_source="SYSTEM", scheduled_start_at=None,
        )
        ensure.assert_called_once()
        db.commit.assert_called_once()

    def test_manual_scheduler_does_not_create_new_game(self):
        self.config.scheduler_mode = "MANUAL"
        state, db, create, _, _, _ = self.execute_level()
        self.assertEqual(state, "no_active_manual_scheduler")
        create.assert_not_called()
        db.commit.assert_not_called()

    def test_runtime_off_does_not_even_request_redis_lock(self):
        with (
            patch("app.services.game_autopilot_worker.cfg.GAME_AUTOPILOT_RUNTIME_ENABLED", False),
            patch("app.services.game_autopilot_worker.RedisLock") as lock,
        ):
            stats = GameAutopilotWorker.run_once()
        self.assertFalse(stats["runtime_enabled"])
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(stats["levels"], {})
        lock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
