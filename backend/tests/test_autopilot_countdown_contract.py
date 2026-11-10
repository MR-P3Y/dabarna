"""Read-only regression for Autopilot-authoritative game start countdown.

No financial tables, migrations or production configuration are modified.
"""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "app"


class AutopilotStartCountdownContract(unittest.TestCase):
    def test_existing_worker_owns_the_30_second_deadline(self):
        src = (ROOT / "services" / "game_autopilot_worker.py").read_text(encoding="utf-8")
        self.assertIn("game.scheduled_start_at = now + timedelta(", src)
        self.assertIn("config.countdown_seconds or 30", src)
        self.assertIn('str(config.start_mode or "MANUAL").upper() != "AUTO"', src)
        self.assertIn("GameService.start_game(", src)

    def test_user_timer_exposes_server_time_and_obeys_autopilot_gate(self):
        schema = (ROOT / "schemas" / "mini.py").read_text(encoding="utf-8")
        src = (ROOT / "routers" / "mini_router.py").read_text(encoding="utf-8")
        for key in ("countdown_seconds", "countdown_enabled", "server_time_utc"):
            self.assertIn(key, schema)
            self.assertIn(key, src)
        self.assertIn('cfg.GAME_AUTOPILOT_RUNTIME_ENABLED', src)
        self.assertIn('str(config.start_mode or "MANUAL").upper() == "AUTO"', src)
        self.assertIn('func.count(func.distinct(GameCard.user_id))', src)
        self.assertIn('str(game.execution_source or "ADMIN").upper() == "SYSTEM"', src)

    def test_bot_report_has_matching_schedule_and_permissions(self):
        src = (ROOT / "routers" / "bot_router.py").read_text(encoding="utf-8")
        for marker in (
            'countdown_enabled=bool(countdown_enabled)',
            'scheduled_start_at=_as_str_datetime(game["scheduled_start_at"])',
            'str(game["execution_source"] or "ADMIN").upper() == "SYSTEM"',
            'cfg.GAME_AUTOPILOT_RUNTIME_ENABLED',
            'GameAutopilotConfig',
            'func.count(func.distinct(GameCard.user_id))',
        ):
            self.assertIn(marker, src)
        ast.parse(src)

    def test_no_new_start_scheduler_in_ui(self):
        src = (ROOT / "static" / "mini" / "app.js").read_text(encoding="utf-8")
        begin = src.index("let gameStartCountdownTicker = null;")
        end = src.index("\nfunction drawGames(items) {", begin)
        helper = src[begin:end]
        self.assertIn("autopilotGameStartClock", helper)
        self.assertNotIn("apiFetch(", helper)
        self.assertNotIn("start_game(", helper)


if __name__ == "__main__":
    unittest.main()
