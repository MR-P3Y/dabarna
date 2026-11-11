import unittest

from bot.keyboards.admin_games import admin_winners_archive_kb


class WinnerArchiveLabelsTests(unittest.TestCase):
    @staticmethod
    def button_text_for(rule):
        kb = admin_winners_archive_kb(
            [{
                "id": 777,
                "game_rule": rule,
                "card_layout_version": 1 if rule == "LEGACY" else 2,
                "col_count": 1,
                "row_count": 2,
                "card_price": 5000,
            }],
            offset=0, has_next=False,
        )
        matches = [
            button.text for row in kb.inline_keyboard for button in row
            if button.callback_data and button.callback_data.startswith("admin:games:winners:777:")
        ]
        assert len(matches) == 1
        return matches[0]

    def test_full_card_does_not_show_torna(self):
        label = self.button_text_for("FULL_CARD")
        self.assertIn("پرکردنی:2", label)
        self.assertNotIn("تورنا", label)

    def test_line_uses_torna_and_line(self):
        label = self.button_text_for("LINE")
        self.assertIn("تورنا:1", label)
        self.assertIn("خطی:2", label)

    def test_legacy_keeps_legacy_labels(self):
        label = self.button_text_for("LEGACY")
        self.assertIn("ستونی:1", label)
        self.assertIn("ردیفی:2", label)


if __name__ == "__main__":
    unittest.main()
