"""Autopilot countdown: no second scheduler, correct forum lane, no duplicates."""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:TEST_ONLY")

from bot.config import settings
from bot.workers import notifier


class CountdownNoticeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.group = -1001234567890
        self.deadline = datetime.now(timezone.utc) + timedelta(seconds=25)
        self.game = {
            "id": 91,
            "tg_group_id": self.group,
            "tg_topic_id": 6,
            "status": "LOBBY",
            "execution_source": "SYSTEM",
            "countdown_enabled": True,
            "draw_mode": "AUTO",
            "scheduled_start_at": self.deadline.isoformat(),
        }
        self.report = {"game": self.game}

    async def test_countdown_posts_once_in_correct_game_topic(self):
        with (
            patch.object(settings, "USER_FORUM_CHAT_ID", self.group),
            patch.object(settings, "USER_TOPIC_GAME_LOW_ID", 6),
            patch.object(settings, "USER_TOPIC_LIVE_NUMBERS_ID", 9),
            patch("bot.workers.notifier.get_meta_marker", return_value="") as get_marker,
            patch("bot.workers.notifier.set_meta_marker") as set_marker,
            patch("bot.workers.notifier.send_to_game_topic", new_callable=AsyncMock, return_value=True) as send,
        ):
            sent = await notifier._notify_autopilot_start_countdown(None, game_id=91, report=self.report)
        self.assertTrue(sent)
        get_marker.assert_called_once()
        set_marker.assert_called_once()
        self.assertTrue(set_marker.call_args.args[0].startswith("autopilot_countdown_notice:91"))
        self.assertIn("+00:00", set_marker.call_args.args[1])
        send.assert_awaited_once()
        kw = send.call_args.kwargs
        self.assertEqual(kw["game_topic_id"], 6)
        self.assertFalse(kw["disable_notification"])
        self.assertIn("بازی #91", kw["text"])
        self.assertIn("شماره‌خوان", kw["text"])
        self.assertIn("ثانیه", kw["text"])

    async def test_no_duplicate_when_schedule_is_acknowledged(self):
        schedule = self.deadline.isoformat()
        with (
            patch.object(settings, "USER_FORUM_CHAT_ID", self.group),
            patch.object(settings, "USER_TOPIC_GAME_LOW_ID", 6),
            patch("bot.workers.notifier.get_meta_marker", return_value=schedule),
            patch("bot.workers.notifier.send_to_game_topic", new_callable=AsyncMock) as send,
        ):
            ok = await notifier._notify_autopilot_start_countdown(None, game_id=91, report=self.report)
        self.assertTrue(ok)
        send.assert_not_awaited()

    async def test_no_notice_for_manual_or_started_or_expired_games(self):
        with (
            patch.object(settings, "USER_FORUM_CHAT_ID", self.group),
            patch.object(settings, "USER_TOPIC_GAME_LOW_ID", 6),
            patch("bot.workers.notifier.send_to_game_topic", new_callable=AsyncMock) as send,
        ):
            for override in (
                {"execution_source": "ADMIN"},
                {"countdown_enabled": False},
                {"status": "RUNNING"},
                {"scheduled_start_at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()},
                {"scheduled_start_at": None},
                {"tg_topic_id": 987654},
            ):
                report = {"game": {**self.game, **override}}
                self.assertFalse(await notifier._notify_autopilot_start_countdown(None, game_id=91, report=report))
        send.assert_not_awaited()

    async def test_failed_send_is_not_acknowledged(self):
        with (
            patch.object(settings, "USER_FORUM_CHAT_ID", self.group),
            patch.object(settings, "USER_TOPIC_GAME_LOW_ID", 6),
            patch("bot.workers.notifier.get_meta_marker", return_value=""),
            patch("bot.workers.notifier.set_meta_marker") as mark,
            patch("bot.workers.notifier.send_to_game_topic", new_callable=AsyncMock, return_value=False),
        ):
            self.assertFalse(await notifier._notify_autopilot_start_countdown(None, game_id=91, report=self.report))
        mark.assert_not_called()

    async def test_real_game_started_goes_to_its_own_topic(self):
        report = {"game": {**self.game, "status": "RUNNING"}}
        with (
            patch.object(settings, "USER_FORUM_CHAT_ID", self.group),
            patch.object(settings, "USER_TOPIC_GAME_LOW_ID", 6),
            patch.object(settings, "USER_TOPIC_LIVE_NUMBERS_ID", 9),
            patch("bot.workers.notifier.send_to_game_topic", new_callable=AsyncMock, return_value=True) as send,
        ):
            result = await notifier._send_game_started_to_lane(
                None, game_id=91, report=report,
                event={"payload_json": {"draw_mode": "AUTO", "draw_interval_seconds": 5}},
            )
        self.assertTrue(result)
        send.assert_awaited_once()
        kw = send.call_args.kwargs
        self.assertEqual(kw["game_topic_id"], 6)
        self.assertIn("شروع شد", kw["text"])
        self.assertIn("هر <b>5 ثانیه</b>", kw["text"])


if __name__ == "__main__":
    unittest.main()
