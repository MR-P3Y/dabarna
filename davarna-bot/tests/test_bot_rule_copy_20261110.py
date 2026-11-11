"""Rule-specific Telegram bot copy and stable grid rendering regressions."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from bot.services.card_render import render_number_grid_with_marks
from bot.services.game_rules import card_progress, rule_details, rule_kind, rule_title


BOT = Path(__file__).resolve().parents[1] / "bot"
ROOT = BOT.parents[1]


class BotGameRuleCopyTests(unittest.TestCase):
    def setUp(self):
        self.line = {"game_rule": "LINE", "card_layout_version": 2}
        self.full = {"game_rule": "FULL_CARD", "card_layout_version": 2}
        self.legacy = {"game_rule": "LEGACY", "card_layout_version": 1}
        self.card_v2 = [
            1, 12, 0, 36, 0, 0, 61, 0, 80,
            3, 0, 21, 0, 42, 50, 0, 72, 0,
            0, 19, 27, 0, 48, 59, 0, 0, 81,
        ]
        self.card_old = list(range(1, 21))

    def test_line_rule(self):
        self.assertEqual(rule_kind(self.line), "LINE")
        self.assertEqual(rule_title(self.line), "خطی")
        detail = rule_details(self.line)
        self.assertIn("۳ ردیف × ۹ ستون", detail)
        self.assertIn("تورنا", detail)
        self.assertIn("۳ عدد از یک ردیف", detail)
        self.assertIn("هر ۵ عدد یک ردیف", detail)

    def test_full_card_has_no_intermediate_prize(self):
        self.assertEqual(rule_title(self.full), "پرکردنی")
        detail = rule_details(self.full)
        self.assertIn("هر ۱۵ عدد", detail)
        self.assertIn("بدون تورنا", detail)

    def test_legacy_is_not_misclassified_as_v2(self):
        self.assertEqual(rule_title(self.legacy), "قدیمی ۲۰عددی")
        self.assertIn("۴ ردیف × ۵ ستون", rule_details(self.legacy))
        self.assertIn("ستون ۴عددی", rule_details(self.legacy))
        self.assertEqual(rule_kind({"game_rule": "LINE", "card_layout_version": 1}), "UNKNOWN")

    def test_card_grid_preserves_width_when_called_numbers_change(self):
        original = render_number_grid_with_marks(self.card_v2, [], self.line)
        updated = render_number_grid_with_marks(self.card_v2, [1, 36, 12, 59], self.line)
        self.assertEqual(len(original.splitlines()), 3)
        self.assertEqual(len(updated.splitlines()), 3)
        self.assertEqual([len(x) for x in original.splitlines()],
                         [len(x) for x in updated.splitlines()])
        self.assertEqual([len(x) for x in updated.splitlines()], [35, 35, 35])
        self.assertIn("✓01", updated)
        self.assertIn(" · ", updated)

    def test_old_card_stays_four_by_five(self):
        result = render_number_grid_with_marks(self.card_old, [1, 20], self.legacy)
        self.assertEqual(len(result.splitlines()), 4)
        self.assertEqual([len(x) for x in result.splitlines()], [19] * 4)

    def test_progress_not_confused_with_winner_confirmation(self):
        progress = card_progress(self.card_v2, [1, 36, 12], self.line)
        self.assertIn("3/15", progress)
        self.assertIn("1: 3/۵", progress)
        self.assertNotIn("برنده شد", progress)
        self.assertNotIn("پرداخت شد", progress)

    def test_all_card_views_use_one_rule_aware_builder(self):
        router = (BOT / "routers" / "cards.py").read_text(encoding="utf-8")
        ast.parse(router)
        self.assertEqual(router.count("text = _card_message("), 5)
        self.assertNotIn("cols=5", router)

    def test_purchase_and_game_views_use_same_rule_definitions(self):
        for name in ("game.py", "purchase.py"):
            src = (BOT / "routers" / name).read_text(encoding="utf-8")
            ast.parse(src)
            self.assertIn("rule_details(", src)
        api = (ROOT / "backend" / "app" / "routers" / "bot_router.py").read_text(encoding="utf-8")
        ast.parse(api)
        self.assertIn('game_rule=g.game_rule', api)


if __name__ == "__main__":
    unittest.main()
