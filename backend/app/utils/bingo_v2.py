"""Version 2: traditional 3x9 Tambola/Dabarna cards.

The legacy 4x5/20-number card format remains in app.utils.bingo.
A V2 card is stored as 27 row-major integers. Zero represents an empty cell,
not a called or playable number. Every row contains exactly five numbers.
"""

from __future__ import annotations

import hashlib
import random
from typing import Iterable, Sequence

ROWS = 3
COLS = 9
NUMBERS_PER_ROW = 5
NUMBERS_PER_CARD = ROWS * NUMBERS_PER_ROW
EMPTY = 0

# In the last column both the eighties AND number 90 are valid.
COLUMN_RANGES: tuple[tuple[int, int], ...] = (
    (1, 9),
    (10, 19),
    (20, 29),
    (30, 39),
    (40, 49),
    (50, 59),
    (60, 69),
    (70, 79),
    (80, 90),
)


def _rng(seed: str) -> random.Random:
    if not isinstance(seed, str) or not seed:
        raise ValueError("seed must be a non-empty string")
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest, "big"))


def generate_tambola_card(seed: str) -> list[int]:
    """Produce a deterministic, valid traditional card in row-major order.

    The caller must include an unpredictable nonce in production seeds.
    Every column has >=1 number; every row has exactly 5; each column is
    sorted from top to bottom; blank cells are represented by integer 0.
    """
    rng = _rng(seed)
    grid = [[EMPTY for _ in range(COLS)] for _ in range(ROWS)]

    # Assign one number slot to each column, balancing 3 initial slots/row.
    columns = list(range(COLS))
    rng.shuffle(columns)
    for i, column in enumerate(columns):
        grid[i % ROWS][column] = -1  # slot placeholder, not a playable number

    # Give each row two additional, independently randomized slots.
    for row in rng.sample(list(range(ROWS)), ROWS):
        available = [col for col in range(COLS) if grid[row][col] == EMPTY]
        for col in rng.sample(available, 2):
            grid[row][col] = -1

    for col, (low, high) in enumerate(COLUMN_RANGES):
        occupied = [row for row in range(ROWS) if grid[row][col] == -1]
        values = sorted(rng.sample(range(low, high + 1), len(occupied)))
        for row, number in zip(occupied, values):
            grid[row][col] = number

    numbers = [number for row in grid for number in row]
    if not is_valid_tambola_card(numbers):
        raise RuntimeError("generated card did not pass layout validation")
    return numbers


def is_valid_tambola_card(numbers: Sequence[int]) -> bool:
    if not isinstance(numbers, (list, tuple)) or len(numbers) != ROWS * COLS:
        return False
    if any(type(n) is not int or n < 0 for n in numbers):
        return False

    used: list[int] = []
    for row in range(ROWS):
        values = numbers[row * COLS:(row + 1) * COLS]
        if sum(n > 0 for n in values) != NUMBERS_PER_ROW:
            return False
        used.extend(n for n in values if n > 0)

    if len(used) != NUMBERS_PER_CARD or len(set(used)) != NUMBERS_PER_CARD:
        return False

    for col, (low, high) in enumerate(COLUMN_RANGES):
        values = [numbers[row * COLS + col] for row in range(ROWS)]
        filled = [n for n in values if n > 0]
        if not filled or any(n < low or n > high for n in filled):
            return False
        if filled != sorted(filled):
            return False
    return True


def _rows(numbers: Sequence[int]) -> list[list[int]]:
    if not is_valid_tambola_card(numbers):
        raise ValueError("invalid Tambola V2 card")
    return [
        [n for n in numbers[row * COLS:(row + 1) * COLS] if n != EMPTY]
        for row in range(ROWS)
    ]


def is_tourna(numbers: Sequence[int], called: Iterable[int]) -> bool:
    """LINE mode: any three of the five numbers in a single row are called."""
    called_set = {int(n) for n in called if int(n) > 0}
    return any(sum(n in called_set for n in row) >= 3 for row in _rows(numbers))


def is_line_complete(numbers: Sequence[int], called: Iterable[int]) -> bool:
    """LINE mode: all five numbers of any one row are called."""
    called_set = {int(n) for n in called if int(n) > 0}
    return any(all(n in called_set for n in row) for row in _rows(numbers))


def is_full_card(numbers: Sequence[int], called: Iterable[int]) -> bool:
    """FULL_CARD mode: all fifteen playable numbers are called."""
    called_set = {int(n) for n in called if int(n) > 0}
    return all(n in called_set for row in _rows(numbers) for n in row)
