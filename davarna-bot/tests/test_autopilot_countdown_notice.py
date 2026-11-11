"""Autopilot countdown: no second scheduler, correct forum lane, no duplicates."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:TEST_ONLY")

from bot.config import settings
from bot.services import notify_store
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
            "game_level": "LOW",
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
            patch("bot.workers.notifier.send_to_user_topic", new_callable=AsyncMock, return_value=True) as announce,
        ):
            sent = await notifier._notify_autopilot_start_countdown(None, game_id=91, report=self.report)
        self.assertTrue(sent)
        self.assertEqual(get_marker.call_count, 2)
        self.assertEqual(set_marker.call_count, 2)
        ack_keys = {call.args[0] for call in set_marker.call_args_list}
        self.assertEqual(ack_keys, {"autopilot_countdown_notice:91:game", "autopilot_countdown_notice:91:announce"})
        self.assertTrue(all("+00:00" in call.args[1] for call in set_marker.call_args_list))
        send.assert_awaited_once()
        announce.assert_awaited_once()
        self.assertEqual(announce.call_args.kwargs["name"], "announce")
        kw = send.call_args.kwargs
        self.assertEqual(kw["game_topic_id"], 6)
        self.assertFalse(kw["disable_notification"])
        self.assertIn("بازی #91", kw["text"])
        self.assertIn("شماره‌خوان", kw["text"])
        self.assertIn("ثانیه", kw["text"])

    async def test_disk_ack_retry_changed_deadline_and_real_forum_routes(self):
        # A fresh get_meta_marker call reads the file anew on every delivery.
        bot = AsyncMock()
        bot.send_message.side_effect = [True, RuntimeError("temporary failure"), True, True, True]
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(notify_store, "_STORE_PATH", Path(tmp) / "acks.json"),
            patch.object(settings, "USER_FORUM_CHAT_ID", self.group),
            patch.object(settings, "USER_TOPIC_GAME_LOW_ID", 6),
            patch.object(settings, "USER_TOPIC_ANNOUNCE_ID", 3),
        ):
            self.assertFalse(await notifier._notify_autopilot_start_countdown(bot, game_id=91, report=self.report))
            self.assertTrue(await notifier._notify_autopilot_start_countdown(bot, game_id=91, report=self.report))
            self.assertTrue(await notifier._notify_autopilot_start_countdown(bot, game_id=91, report=self.report))
            self.game["countdown_seconds"] = 90
            self.game["scheduled_start_at"] = (self.deadline + timedelta(seconds=50)).isoformat()
            self.assertTrue(await notifier._notify_autopilot_start_countdown(bot, game_id=91, report=self.report))
            calls = [call.kwargs for call in bot.send_message.await_args_list]
            self.assertEqual([call["message_thread_id"] for call in calls], [6, 3, 3, 6, 3])
            self.assertTrue(all(call["chat_id"] == self.group for call in calls))
            self.assertTrue(all("شروع شد" not in call["text"] for call in calls))

    async def test_no_duplicate_when_schedule_is_acknowledged(self):
        schedule = self.deadline.isoformat()
        with (
            patch.object(settings, "USER_FORUM_CHAT_ID", self.group),
            patch.object(settings, "USER_TOPIC_GAME_LOW_ID", 6),
            patch("bot.workers.notifier.get_meta_marker", return_value=schedule),
            patch("bot.workers.notifier.send_to_game_topic", new_callable=AsyncMock) as send,
            patch("bot.workers.notifier.send_to_user_topic", new_callable=AsyncMock) as announce,
        ):
            ok = await notifier._notify_autopilot_start_countdown(None, game_id=91, report=self.report)
        self.assertTrue(ok)
        send.assert_not_awaited()
        announce.assert_not_awaited()

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
                {"game_level": "HIGH"},
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
            patch("bot.workers.notifier.send_to_user_topic", new_callable=AsyncMock, return_value=True),
        ):
            self.assertFalse(await notifier._notify_autopilot_start_countdown(None, game_id=91, report=self.report))
        mark.assert_called_once_with("autopilot_countdown_notice:91:announce", self.deadline.isoformat())

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
