import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:TEST_ONLY")

from bot.config import settings
from bot.workers import notifier


class PublicForumNoticeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.group_id = -1001234567890
        self.report = {
            "game": {
                "tg_group_id": self.group_id,
                "tg_topic_id": 6,
                "card_price": 5000,
                "game_rule": "LINE",
                "prize_pool": 9000,
            },
            "purchases": {"cards_sold": 2},
            "called_numbers": [],
        }

    async def test_created_notice_uses_only_announcement_and_links_to_game(self):
        with (
            patch.object(settings, "USER_FORUM_CHAT_ID", self.group_id),
            patch.object(settings, "USER_TOPIC_RULES_ID", 10),
            patch.object(settings, "USER_TOPIC_GAME_LOW_ID", 6),
            patch("bot.workers.notifier.send_to_user_topic", new_callable=AsyncMock) as send,
        ):
            await notifier._send_user_game_created_notice(
                bot=None, game_id=88, report=self.report, event={}
            )
        send.assert_awaited_once()
        kw = send.call_args.kwargs
        self.assertEqual(kw["name"], "announce")
        self.assertIn("بازی #88", kw["text"])
        self.assertIn("تورنا", kw["text"])
        self.assertIn("ربات را خصوصی", kw["text"])
        self.assertLess(len(kw["text"]), 350)
        self.assertIsNotNone(kw["reply_markup"])
        urls = [b.url for row in kw["reply_markup"].inline_keyboard for b in row]
        self.assertIn("https://t.me/c/1234567890/6", urls)

    async def test_start_has_live_navigation_and_true_rule(self):
        with (
            patch.object(settings, "USER_FORUM_CHAT_ID", self.group_id),
            patch.object(settings, "USER_TOPIC_LIVE_NUMBERS_ID", 9),
            patch.object(settings, "USER_TOPIC_GAME_LOW_ID", 6),
            patch("bot.workers.notifier.send_to_user_topic", new_callable=AsyncMock) as send,
        ):
            await notifier._send_user_game_started_notice(
                bot=None, game_id=88, report=self.report,
                event={"payload_json": {"draw_mode": "MANUAL"}},
            )
        send.assert_awaited_once()
        kw = send.call_args.kwargs
        self.assertEqual(kw["name"], "announce")
        self.assertIn("شروع شد", kw["text"])
        self.assertIn("۵ عدد", kw["text"])
        urls = [b.url for row in kw["reply_markup"].inline_keyboard for b in row]
        self.assertIn("https://t.me/c/1234567890/9", urls)

    async def test_live_number_is_short_without_extra_keyboard(self):
        with patch(
            "bot.workers.notifier.send_to_user_topic", new_callable=AsyncMock
        ) as send:
            await notifier._send_user_live_number_notice(
                bot=None, game_id=88, game_topic_id=6,
                number=32, called_numbers=[4, 18, 32],
            )
        kw = send.call_args.kwargs
        self.assertEqual(kw["name"], "live")
        self.assertIn("عدد 32", kw["text"])
        self.assertNotIn("reply_markup", kw)
        self.assertLess(len(kw["text"]), 100)


if __name__ == "__main__":
    unittest.main()
