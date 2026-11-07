"""Regression: Mini App game creation posts once, not in two user threads."""
import ast
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "app" / "routers" / "mini_router.py"


class UserForumCreatedNoticeTests(unittest.TestCase):
    def test_created_notice_one_send_and_announcement_first(self):
        root = ast.parse(SOURCE.read_text(encoding="utf-8"))
        fun = next(
            x for x in root.body
            if isinstance(x, ast.FunctionDef)
            and x.name == "_mini_send_game_created_notice"
        )
        sends = [
            x for x in ast.walk(fun)
            if isinstance(x, ast.Call)
            and isinstance(x.func, ast.Name)
            and x.func.id == "_mini_send_topic_message"
        ]
        self.assertEqual(len(sends), 1)
        body = ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), fun)
        self.assertIn("announce_id if announce_id is not None else game_topic_id", body)
        self.assertIn("inline_keyboard", body)
        self.assertNotIn("targets.append(", body)

    def test_no_financial_details_exposed_in_public_announcement(self):
        root = ast.parse(SOURCE.read_text(encoding="utf-8"))
        fun = next(x for x in root.body if isinstance(x, ast.FunctionDef)
                   and x.name == "_mini_send_game_created_notice")
        strings = [
            x.value for x in ast.walk(fun)
            if isinstance(x, ast.Constant) and isinstance(x.value, str)
        ]
        text = " ".join(strings)
        self.assertNotIn("شماره کارت بانکی", text)
        self.assertNotIn("wallet_id", text)
        self.assertIn("ربات را خصوصی", text)


if __name__ == "__main__":
    unittest.main()
