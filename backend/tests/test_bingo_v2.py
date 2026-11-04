from __future__ import annotations

import unittest

from app.utils.bingo_v2 import (
    COLS,
    NUMBERS_PER_CARD,
    ROWS,
    generate_tambola_card,
    is_full_card,
    is_line_complete,
    is_tourna,
    is_valid_tambola_card,
)


class TambolaCardV2Tests(unittest.TestCase):
    def test_many_seeds_produce_valid_unique_layouts(self) -> None:
        fingerprints: set[tuple[int, ...]] = set()
        for index in range(1000):
            card = generate_tambola_card(f"game:v2:test:{index}")
            self.assertTrue(is_valid_tambola_card(card))
            self.assertEqual(len(card), ROWS * COLS)
            self.assertEqual(len([n for n in card if n > 0]), NUMBERS_PER_CARD)
            fingerprints.add(tuple(card))
            for row in range(ROWS):
                self.assertEqual(
                    len([n for n in card[row * COLS:(row + 1) * COLS] if n > 0]),
                    5,
                )
        self.assertEqual(len(fingerprints), 1000)

    def test_same_seed_gives_identical_card(self) -> None:
        self.assertEqual(generate_tambola_card("stable"), generate_tambola_card("stable"))

    def test_ninety_is_allowed_only_in_last_column(self) -> None:
        card = generate_tambola_card("ninety-test")
        self.assertTrue(is_valid_tambola_card(card))
        # Every valid card generated must assign the 80..90 bucket to the final column.
        for row in range(ROWS):
            for col in range(COLS):
                n = card[row * COLS + col]
                if n == 90:
                    self.assertEqual(col, 8)

        # Force a valid last-column number to 90 (if necessary) while
        # preserving column ordering and without any duplicate.
        card = generate_tambola_card("last-column")
        last_rows = [r for r in range(ROWS) if card[r * COLS + 8] > 0]
        last_index = last_rows[-1] * COLS + 8
        card[last_index] = 90
        self.assertTrue(is_valid_tambola_card(card))

    def test_tourna_is_any_three_of_one_row_not_first_three_columns(self) -> None:
        card = generate_tambola_card("three-of-five")
        first_row = [n for n in card[:COLS] if n]
        called = [first_row[0], first_row[2], first_row[4]]
        self.assertTrue(is_tourna(card, called))
        self.assertFalse(is_line_complete(card, called))

    def test_three_across_different_rows_is_not_tourna(self) -> None:
        card = generate_tambola_card("one-per-row")
        called = [
            next(n for n in card[r * COLS:(r + 1) * COLS] if n)
            for r in range(ROWS)
        ]
        self.assertFalse(is_tourna(card, called))

    def test_line_requires_five_in_same_row(self) -> None:
        card = generate_tambola_card("line")
        row = [n for n in card[COLS:2 * COLS] if n]
        self.assertFalse(is_line_complete(card, row[:4]))
        self.assertTrue(is_line_complete(card, row))

    def test_full_requires_all_fifteen_numbers(self) -> None:
        card = generate_tambola_card("full")
        values = [n for n in card if n > 0]
        self.assertFalse(is_full_card(card, values[:-1]))
        self.assertTrue(is_full_card(card, values))

    def test_blank_zero_is_not_a_called_number(self) -> None:
        card = generate_tambola_card("blanks")
        self.assertFalse(is_tourna(card, [0]))
        self.assertFalse(is_line_complete(card, [0]))
        self.assertFalse(is_full_card(card, [0]))

    def test_reject_invalid_layout(self) -> None:
        card = generate_tambola_card("invalid")
        bad_card = card.copy()
        idx = next(i for i, n in enumerate(bad_card) if n)
        bad_card[idx] = 0
        self.assertFalse(is_valid_tambola_card(bad_card))
        with self.assertRaises(ValueError):
            is_tourna(bad_card, [])


if __name__ == "__main__":
    unittest.main()
