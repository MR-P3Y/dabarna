from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.services.game_service import GameService
from app.utils.bingo_v2 import generate_tambola_card


class GameV2DispatchTests(unittest.TestCase):
    @staticmethod
    def _card(numbers, card_id=1):
        return SimpleNamespace(id=card_id, user_id=4, numbers_json=numbers)

    def test_line_tourna_uses_any_three_numbers_in_one_row(self) -> None:
        nums = generate_tambola_card("line-tourna")
        row = [n for n in nums[:9] if n > 0]
        cards = [self._card(nums)]
        matches = GameService._winner_cards(
            cards, {row[0], row[2], row[4]}, "COL",
            layout_version=2, game_rule="LINE",
        )
        self.assertEqual(matches, [(1, 4)])
        self.assertEqual(
            GameService._winner_cards(
                cards, set(row[:4]), "ROW",
                layout_version=2, game_rule="LINE",
            ),
            [],
        )

    def test_line_five_numbers_finish(self) -> None:
        nums = generate_tambola_card("line-five")
        row = [n for n in nums[9:18] if n > 0]
        self.assertEqual(
            GameService._winner_cards(
                [self._card(nums)], set(row), "ROW",
                layout_version=2, game_rule="LINE",
            ),
            [(1, 4)],
        )

    def test_full_card_has_no_tourna_and_requires_all_fifteen(self) -> None:
        nums = generate_tambola_card("full-card")
        values = [n for n in nums if n > 0]
        card = self._card(nums)
        self.assertEqual(
            GameService._winner_cards(
                [card], set(values), "COL",
                layout_version=2, game_rule="FULL_CARD",
            ),
            [],
        )
        self.assertEqual(
            GameService._winner_cards(
                [card], set(values[:-1]), "ROW",
                layout_version=2, game_rule="FULL_CARD",
            ),
            [],
        )
        self.assertEqual(
            GameService._winner_cards(
                [card], set(values), "ROW",
                layout_version=2, game_rule="FULL_CARD",
            ),
            [(1, 4)],
        )

    def test_legacy_card_still_uses_original_five_by_four_rules(self) -> None:
        legacy = list(range(1, 21))
        called_row = set(legacy[:5])
        self.assertEqual(
            GameService._winner_cards(
                [self._card(legacy)], called_row, "ROW",
                layout_version=1, game_rule="LEGACY",
            ),
            [(1, 4)],
        )

    def test_invalid_v2_rule_fails_closed(self) -> None:
        nums = generate_tambola_card("bad-rule")
        with self.assertRaises(ValueError):
            GameService._winner_cards(
                [self._card(nums)], set(), "ROW",
                layout_version=2, game_rule="LEGACY",
            )


if __name__ == "__main__":
    unittest.main()
