import os
import unittest
from unittest.mock import patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:TEST_ONLY")

from bot.config import settings
from bot.services.user_forum_navigation import (
    group_guide_text,
    navigation_keyboard,
    thread_url,
)


class UserForumNavigationTests(unittest.TestCase):
    def test_supergroup_topic_deeplink_and_invalid_ids(self):
        self.assertEqual(thread_url(-1001234567890, 6), "https://t.me/c/1234567890/6")
        self.assertIsNone(thread_url(-1001234567890, None))
        self.assertIsNone(thread_url(-1001234567890, 0))
        self.assertIsNone(thread_url(123456789, 6))
        self.assertIsNone(thread_url(-1999999, 6))

    def test_compact_announcement_navigation(self):
        with (
            patch.object(settings, "USER_FORUM_CHAT_ID", -1001234567890),
            patch.object(settings, "USER_TOPIC_LIVE_NUMBERS_ID", 8),
            patch.object(settings, "USER_TOPIC_RESULTS_ID", 9),
            patch.object(settings, "USER_TOPIC_RULES_ID", 10),
        ):
            menu = navigation_keyboard(game_topic_id=6, show_live=True, show_rules=True)
        self.assertIsNotNone(menu)
        buttons = [item for row in menu.inline_keyboard for item in row]
        self.assertEqual(len(buttons), 3)
        self.assertEqual({b.url for b in buttons}, {
            "https://t.me/c/1234567890/6",
            "https://t.me/c/1234567890/8",
            "https://t.me/c/1234567890/10",
        })

    def test_no_dead_links_and_no_duplicate_buttons(self):
        with (
            patch.object(settings, "USER_FORUM_CHAT_ID", -1001234567890),
            patch.object(settings, "USER_TOPIC_LIVE_NUMBERS_ID", 6),
            patch.object(settings, "USER_TOPIC_RESULTS_ID", None),
            patch.object(settings, "USER_TOPIC_RULES_ID", None),
        ):
            menu = navigation_keyboard(game_topic_id=6, show_live=True, show_results=True)
        self.assertEqual(len([x for row in menu.inline_keyboard for x in row]), 1)
        self.assertIsNone(thread_url(None, 6))
        with patch.object(settings, "USER_FORUM_CHAT_ID", None):
            self.assertIsNone(navigation_keyboard(game_topic_id=6))

    def test_guide_lists_all_eight_user_areas_in_plain_language(self):
        with (
            patch.object(settings, "USER_FORUM_CHAT_ID", -1001234567890),
            patch.object(settings, "USER_TOPIC_ANNOUNCE_ID", 3),
            patch.object(settings, "USER_TOPIC_GAME_LOW_ID", 6),
            patch.object(settings, "USER_TOPIC_GAME_MEDIUM_ID", 7),
            patch.object(settings, "USER_TOPIC_GAME_HIGH_ID", 8),
            patch.object(settings, "USER_TOPIC_LIVE_NUMBERS_ID", 9),
            patch.object(settings, "USER_TOPIC_RESULTS_ID", 10),
            patch.object(settings, "USER_TOPIC_RULES_ID", 11),
            patch.object(settings, "USER_TOPIC_CHAT_ID", 12),
        ):
            text = group_guide_text()
        for word in ("اعلان‌ها", "بازی ۱", "بازی ۲", "بازی ۳", "اعداد زنده",
                     "نتایج", "قوانین", "گفت‌وگو", "کیف پول"):
            self.assertIn(word, text)
        self.assertEqual(text.count("https://t.me/c/1234567890/"), 8)
        self.assertLess(len(text), 4000)


if __name__ == "__main__":
    unittest.main()
