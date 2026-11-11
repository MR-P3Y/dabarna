import ast
import os
from pathlib import Path
import unittest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:TEST_ONLY")

from bot.routers.wallet import _tx_reason_fa


class BotNotificationRuleConsistencyTests(unittest.TestCase):
    def test_wallet_full_card_prize(self):
        self.assertIn("پرکردنی", _tx_reason_fa("PRIZE_ROW", game_rule="FULL_CARD"))
        self.assertNotIn("تورنا", _tx_reason_fa("PRIZE_ROW", game_rule="FULL_CARD"))

    def test_wallet_line_prizes(self):
        self.assertIn("خطی", _tx_reason_fa("PRIZE_ROW", game_rule="LINE"))
        self.assertIn("۵ عدد", _tx_reason_fa("PRIZE_ROW", game_rule="LINE"))
        self.assertIn("تورنا", _tx_reason_fa("PRIZE_COL", game_rule="LINE"))
        self.assertIn("۳ عدد", _tx_reason_fa("PRIZE_COL", game_rule="LINE"))

    def test_wallet_legacy_prizes(self):
        self.assertIn("ستونی", _tx_reason_fa("PRIZE_COL", game_rule="LEGACY"))
        self.assertIn("ردیفی", _tx_reason_fa("PRIZE_ROW", game_rule="LEGACY"))

    def test_wallet_old_response_is_compatible(self):
        # Missing stored metadata must not invent a legacy rule.
        self.assertIn("قابل تأیید نیست", _tx_reason_fa("PRIZE_ROW"))
        self.assertIn("خرید کارت", _tx_reason_fa("BUY_CARDS"))

    def test_notifier_announces_stored_rule_not_topic(self):
        notifier = Path(__file__).resolve().parents[1] / "bot" / "workers" / "notifier.py"
        module = ast.parse(notifier.read_text(encoding="utf-8"))
        target = next(
            node for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "_game_rule_notice_line"
        )
        from bot.services.game_rules import rule_kind
        namespace = {"rule_kind": rule_kind}
        exec(compile(ast.Module(body=[target], type_ignores=[]), str(notifier), "exec"), namespace)
        announce = namespace["_game_rule_notice_line"]
        full = announce({"game_rule": "FULL_CARD", "card_layout_version": 2})
        line = announce({"game_rule": "LINE", "card_layout_version": 2})
        legacy = announce({"game_rule": "LEGACY", "card_layout_version": 1})
        self.assertIn("۱۵ عدد", full)
        self.assertIn("بدون تورنا", full)
        self.assertIn("۳ عدد از یک ردیف", line)
        self.assertIn("۵ عدد از یک ردیف", line)
        self.assertIn("ستون ۴ عددی", legacy)
        self.assertIn("ردیف ۵ عددی", legacy)

    def test_group_messages_include_rule(self):
        notifier = (Path(__file__).resolve().parents[1] / "bot" / "workers" / "notifier.py").read_text(encoding="utf-8")
        for name in (
            "_send_user_game_started_notice",
            "_send_user_game_created_notice",
            "_send_user_game_ended_notice",
        ):
            self.assertIn("async def " + name, notifier)
        self.assertEqual(notifier.count('f"{_game_rule_notice_line(game)}"'), 3)


if __name__ == "__main__":
    unittest.main()
