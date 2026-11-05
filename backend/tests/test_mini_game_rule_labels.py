import unittest

from app.routers.mini_router import _guess_win_pattern, _prize_label_for_rule


class MiniGameRuleLabelsTests(unittest.TestCase):
    def test_legacy_card_prizes_remain_legacy(self):
        self.assertIn("ستونی", _prize_label_for_rule("PRIZE_COL", "LEGACY"))
        self.assertIn("سطری", _prize_label_for_rule("PRIZE_ROW", "LEGACY"))

    def test_line_uses_three_and_five_from_same_row(self):
        self.assertIn("۳ عدد از یک ردیف", _prize_label_for_rule("PRIZE_COL", "LINE"))
        self.assertIn("۵ عدد از یک ردیف", _prize_label_for_rule("PRIZE_ROW", "LINE"))
        self.assertIn("خطی", _guess_win_pattern({1}, {2}, "LINE"))

    def test_full_card_has_fifteen_numbers_no_intermediate_prize(self):
        self.assertEqual(_prize_label_for_rule("PRIZE_ROW", "FULL_CARD"), "برد پرکردنی (۱۵ عدد)")
        self.assertEqual(_guess_win_pattern({1}, set(), "FULL_CARD"), "برد پرکردنی (۱۵ عدد)")
        self.assertEqual(_guess_win_pattern(set(), set(), "FULL_CARD"), "نامشخص")


if __name__ == "__main__":
    unittest.main()
