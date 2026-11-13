from __future__ import annotations

import os
import unittest

# This test never calls Telegram or the backend. A dummy token only allows
# the bot's Settings model to initialize when no .env is mounted.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:TEST_ONLY")

from bot.services.card_render import build_grid_text_from_numbers, render_grid_with_marks
from bot.routers.admin_games import _render_card_grid


V2_NUMBERS = [
    5, 0, 25, 0, 45, 0, 65, 0, 85,
    0, 12, 0, 32, 0, 52, 0, 72, 87,
    7, 0, 27, 0, 47, 0, 67, 0, 90,
]


class BotV2CardLayoutTests(unittest.TestCase):
    def test_user_card_renders_three_rows_without_zero(self):
        txt = build_grid_text_from_numbers(V2_NUMBERS)
        self.assertEqual(len(txt.splitlines()), 3)
        self.assertNotIn("00", txt)
        self.assertIn("90", txt)
        marked = render_grid_with_marks(txt, [5, 25, 90])
        self.assertIn("5✅", marked)
        self.assertIn("90✅", marked)

    def test_admin_winner_card_renders_three_by_nine(self):
        txt = _render_card_grid(V2_NUMBERS, {5, 25, 90}, {"game_rule": "LINE", "card_layout_version": 2})
        lines = txt.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertNotIn("00", txt)
        self.assertIn("✓05", txt)
        self.assertIn("✓25", txt)
        self.assertIn("✓90", txt)
        self.assertIn("·", txt)
        self.assertEqual(txt.count("·"), 12)

    def test_legacy_admin_cards_still_have_four_rows(self):
        txt = _render_card_grid(list(range(1, 21)), {1, 5, 20}, {"game_rule": "LEGACY", "card_layout_version": 1})
        self.assertEqual(len(txt.splitlines()), 4)
        self.assertIn("✓01", txt)
        self.assertIn(" 02", txt)

    def test_invalid_card_is_not_rendered(self):
        self.assertIn("کارت نامعتبر", _render_card_grid([1, 2, 3], {1}, {"game_rule": "LINE", "card_layout_version": 2}))


if __name__ == "__main__":
    unittest.main()
