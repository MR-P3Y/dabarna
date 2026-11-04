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
