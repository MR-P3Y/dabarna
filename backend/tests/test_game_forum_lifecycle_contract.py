"""Cross-surface game rule and forum routing contract (#25/#27/#29).

Offline source-based executable checks. No Telegram bot, production DB, or
financial services are contacted; no topic is created or renamed.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
NOTIFIER = ROOT / "davarna-bot/bot/workers/notifier.py"
TOPICS = ROOT / "davarna-bot/bot/services/user_topics.py"
CONFIG = ROOT / "davarna-bot/bot/config.py"
MINI = ROOT / "backend/app/routers/mini_router.py"


def _function(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


def _load_plain_function(path: Path, name: str, namespace=None):
    future = ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0,
    )
    mod = ast.Module(body=[future, _function(path, name)], type_ignores=[])
    code = compile(ast.fix_missing_locations(mod), str(path), "exec")
    result = dict(namespace or {})
    exec(code, result)
    return result[name]


def _notice_target(name):
    node = _function(NOTIFIER, name)
    calls = [
        v for v in ast.walk(node)
        if isinstance(v, ast.Call)
        and isinstance(v.func, ast.Name)
        and v.func.id == "send_to_user_topic"
    ]
    assert len(calls) == 1, f"{name}: require exactly one forum send"
    return next(kw.value for kw in calls[0].keywords if kw.arg == "name")


class GameForumLifecycleContractTests(unittest.TestCase):
    def test_game_start_topic_is_opt_in_and_defaults_unset(self):
        source = CONFIG.read_text(encoding="utf-8")
        self.assertIn("USER_TOPIC_GAME_START_ID: int | None = None", source)
        selector = _load_plain_function(
            TOPICS, "game_start_announcement_topic",
            {"settings": SimpleNamespace(USER_TOPIC_GAME_START_ID=None)},
        )
        self.assertEqual(selector(), "announce")
        selector.__globals__["settings"] = SimpleNamespace(
            USER_TOPIC_GAME_START_ID=88,
        )
        self.assertEqual(selector(), "game_start")
        selector.__globals__["settings"] = SimpleNamespace(
            USER_TOPIC_GAME_START_ID=0,
        )
        self.assertEqual(selector(), "announce")

    def test_start_event_only_routes_to_separate_thread(self):
        start = _notice_target("_send_user_game_started_notice")
        self.assertIsInstance(start, ast.Call)
        self.assertIsInstance(start.func, ast.Name)
        self.assertEqual(start.func.id, "game_start_announcement_topic")
        for function, expected in (
            ("_send_user_game_created_notice", "announce"),
            ("_send_user_game_ended_notice", "results"),
            ("_send_user_live_number_notice", "live"),
        ):
            target = _notice_target(function)
            self.assertIsInstance(target, ast.Constant)
            self.assertEqual(target.value, expected)

    def test_notifier_and_mini_rule_text_agree(self):
        bot_rule = _load_plain_function(NOTIFIER, "_game_rule_notice_line")
        mini_rule = _load_plain_function(MINI, "_mini_game_rule_announcement_line")
        for rule, required in (
            ("LINE", ("۳ ردیف × ۹ ستون", "۵ عدد در هر ردیف",
                      "تورنا ۳ عدد از یک ردیف", "خطی ۵ عدد از یک ردیف")),
            ("FULL_CARD", ("۱۵ عدد کامل", "بدون تورنا")),
            ("LEGACY", ("۴×۵", "۲۰ عدد", "ستون ۴ عددی")),
        ):
            game = {"game_rule": rule}
            a, b = bot_rule(game), mini_rule(rule)
            self.assertEqual(a, b, rule)
            for phrase in required:
                self.assertIn(phrase, a, (rule, phrase))
            self.assertTrue(a.endswith("\n"))
            self.assertNotIn("\\n", a, "unexpected literal backslash newline")
        self.assertEqual(bot_rule({}), mini_rule(None))

    def test_forum_guide_uses_dedicated_start_thread_only_if_configured(self):
        from html import escape

        fields = {
            "USER_FORUM_CHAT_ID": -100987654321,
            "USER_TOPIC_ANNOUNCE_ID": 3,
            "USER_TOPIC_GAME_LOW_ID": 6,
            "USER_TOPIC_GAME_MEDIUM_ID": 8,
            "USER_TOPIC_GAME_HIGH_ID": 10,
            "USER_TOPIC_LIVE_NUMBERS_ID": 12,
            "USER_TOPIC_RESULTS_ID": 14,
            "USER_TOPIC_RULES_ID": 2,
            "USER_TOPIC_CHAT_ID": 4,
            "USER_TOPIC_GAME_START_ID": None,
        }
        settings = SimpleNamespace(**fields)
        guide = _load_plain_function(
            ROOT / "davarna-bot/bot/services/user_forum_navigation.py",
            "group_guide_text",
            {"settings": settings, "escape": escape,
             "topic_link": lambda topic: f"https://test.invalid/{topic}" if topic else None},
        )
        self.assertIn("خبرهای مهم و شروع بازی", guide())
        self.assertNotIn("اطلاعیه شروع بازی", guide())
        settings.USER_TOPIC_GAME_START_ID = 18
        self.assertIn("خبرهای مهم و بازشدن خرید کارت", guide())
        self.assertIn("اطلاعیه شروع بازی", guide())
        self.assertIn("https://test.invalid/18", guide())
        settings.USER_TOPIC_GAME_START_ID = None
        self.assertNotIn("https://test.invalid/18", guide())

    def test_no_unimplemented_five_minute_promise(self):
        source = NOTIFIER.read_text(encoding="utf-8")
        mini = MINI.read_text(encoding="utf-8")
        for text in (source, mini):
            self.assertIn("ساعت شروع قطعی اعلام نشده است", text)
            self.assertNotIn("۵ دقیقه مانده", text)

    def test_mini_announcement_uses_stored_rule(self):
        func = _function(MINI, "_mini_send_game_created_notice")
        calls = [
            item for item in ast.walk(func)
            if isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
            and item.func.id == "_mini_game_rule_announcement_line"
        ]
        self.assertEqual(len(calls), 1)
        self.assertIsInstance(calls[0].args[0], ast.Call)
        self.assertEqual(calls[0].args[0].func.id, "getattr")
        self.assertEqual(calls[0].args[0].args[1].value, "game_rule")


if __name__ == "__main__":
    unittest.main()
