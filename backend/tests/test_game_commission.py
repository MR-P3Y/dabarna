from __future__ import annotations

import os
import unittest
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.services.game_autopilot_config_service import (
    DEFAULT_COMMISSION_RATE,
    GameAutopilotConfigService,
)
from app.services.game_service import GameService


class GameCommissionTests(unittest.TestCase):
    def test_manual_game_zero_commission_is_preserved(self) -> None:
        game = SimpleNamespace(commission_rate=Decimal("0"))
        self.assertEqual(GameService._commission_rate_for_game(game), Decimal("0.0000"))

    def test_missing_game_commission_uses_default_only_as_fallback(self) -> None:
        game = SimpleNamespace(commission_rate=None)
        self.assertEqual(GameService._commission_rate_for_game(game), DEFAULT_COMMISSION_RATE)

    def test_custom_commission_is_normalized(self) -> None:
        self.assertEqual(
            GameAutopilotConfigService.normalize_commission_rate("0.175"),
            Decimal("0.1750"),
        )

    def test_autopilot_serialize_preserves_zero_commission(self) -> None:
        row = SimpleNamespace(
            level="LOW",
            enabled=1,
            scheduler_mode="AUTO",
            start_mode="AUTO",
            draw_mode="AUTO",
            card_price=5000,
            commission_rate=Decimal("0"),
            announce_before_seconds=300,
            countdown_seconds=30,
            repeat_interval_seconds=60,
            draw_interval_seconds=8,
            cooldown_seconds=0,
            min_unique_players=2,
            updated_by=None,
            updated_at=None,
        )
        payload = GameAutopilotConfigService.serialize(row)
        self.assertEqual(payload["commission_rate"], 0.0)
        # Older config-like objects without the V2 field retain the LINE default.
        self.assertEqual(payload["game_rule"], "LINE")

    def test_invalid_commission_is_rejected(self) -> None:
        for value in ("-0.01", "1", "1.5"):
            with self.subTest(value=value):
                with self.assertRaises(Exception):
                    GameAutopilotConfigService.normalize_commission_rate(value)


if __name__ == "__main__":
    unittest.main()
