from html import escape
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


def render_number_grid_with_marks(numbers: list[int], called_numbers: list[int]) -> str:
    """Stable-width Telegram <pre> grid for 3x9 (15 values) and 4x5 (20).

    A checkmark replaces the leading space in each 3-column number cell, so
    marking called numbers does not shift neighboring columns. Zero is blank.
    """
    nums = [int(n) for n in (numbers or [])]
    if len(nums) not in (20, 27):
        raise ValueError("invalid card layout")
    columns = 9 if len(nums) == 27 else 5
    seen = {int(n) for n in (called_numbers or [])}
    rows = []
    for index in range(0, len(nums), columns):
        cells = []
        for value in nums[index:index + columns]:
            if value == 0:
                cells.append(" · ")
            elif value in seen:
                cells.append(f"✓{value:02d}")
            else:
                cells.append(f" {value:02d}")
        rows.append(" ".join(cells))
    return escape("\n".join(rows))
