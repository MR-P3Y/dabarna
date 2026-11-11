from collections.abc import Iterable, Mapping
from html import escape

from bot.services.game_rules import rule_kind
import re


def build_grid_text_from_numbers(numbers: list[int], cols: int = 5) -> str:
    """Render both legacy 4x5 cards and new 3x9 fifteen-number cards."""
    nums = [int(n) for n in (numbers or [])]
    if len(nums) == 27:
        cols = 9
    elif len(nums) != 20:
        return "INVALID_CARD"

    lines = []
    for offset in range(0, len(nums), cols):
        row = nums[offset:offset + cols]
        lines.append("  ".join(f"{n:>2}" if n > 0 else "  " for n in row))
    return "\n".join(lines)


def render_grid_with_marks(grid_text: str, called_numbers: list[int]) -> str:
    called = {int(n) for n in (called_numbers or [])}

    def repl(match: re.Match) -> str:
        n = int(match.group(0))
        return f"{n}✅" if n in called else str(n)

    return escape(re.sub(r"\b\d+\b", repl, grid_text or ""))


def render_number_grid_with_marks(numbers: list[int], called_numbers: Iterable[int], game: Mapping) -> str:
    """Render validated, fixed-width cells using the stored game metadata."""
    kind = rule_kind(game)
    if kind == "UNKNOWN":
        raise ValueError("قانون یا چیدمان ثبت‌شدهٔ بازی ناقص یا ناسازگار است.")
    rows, columns = (4, 5) if kind == "LEGACY" else (3, 9)
    if not isinstance(numbers, list) or len(numbers) != rows * columns:
        raise ValueError("دادهٔ کارت با چیدمان ثبت‌شده ناسازگار است.")
    if any(type(n) is not int or n < 0 or n > 90 for n in numbers):
        raise ValueError("اعداد کارت نامعتبرند.")
    played = [n for n in numbers if n]
    card_rows = [numbers[i:i + columns] for i in range(0, len(numbers), columns)]
    if len(set(played)) != len(played) or any(sum(n > 0 for n in row) != 5 for row in card_rows):
        raise ValueError("اعداد کارت با قانون ثبت‌شده ناسازگارند.")
    if kind != "LEGACY":
        for col, values in enumerate(zip(*card_rows)):
            occupied = [v for v in values if v]
            low, high = max(1, col * 10), (90 if col == 8 else col * 10 + 9)
            if not occupied or occupied != sorted(occupied) or any(not low <= v <= high for v in occupied):
                raise ValueError("اعداد ستون کارت با چیدمان ثبت‌شده ناسازگارند.")
    seen = set(called_numbers)
    width = max(2, len(str(max(played))))
    lines = []
    for row in card_rows:
        cells = []
        for value in row:
            if value == 0:
                cells.append(" · ")
            else:
                mark = "✓" if value in seen else " "
                cells.append(f"{mark}{value:0{width}d}")
        lines.append(" ".join(cells))
    return "\n".join(lines)
