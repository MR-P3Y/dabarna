from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from app.services.game_autopilot_worker import GameAutopilotWorker

class StartRequirementsTests(TestCase):
    def test_configured_conditions(self):
        for mode, players, cards, expected in [
            ("PLAYERS", 3, 3, True), ("PLAYERS", 2, 20, False),
            ("CARDS", 1, 10, True), ("CARDS", 3, 9, False),
            ("BOTH", 3, 10, True), ("BOTH", 2, 10, False),
            ("BOTH", 3, 9, False), ("UNKNOWN", 3, 10, False),
        ]:
            with self.subTest(mode=mode, players=players, cards=cards):
                db = Mock()
                db.execute.return_value.one.return_value = (players, cards)
                config = SimpleNamespace(start_requirement=mode, min_unique_players=3, min_cards_sold=10)
                result = GameAutopilotWorker.readiness(db, 91, config)
                self.assertEqual(result["ready"], expected)
                self.assertEqual(result["minimum_players"], 3 if mode in {"PLAYERS", "BOTH"} else None)
                self.assertEqual(result["minimum_cards"], 10 if mode in {"CARDS", "BOTH"} else None)
