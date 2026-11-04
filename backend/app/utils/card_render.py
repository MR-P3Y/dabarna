from __future__ import annotations

from typing import Iterable


def render_card_text(numbers: list[int], called: Iterable[int], rows: int = 4, cols: int = 5) -> str:
    """Render legacy 4x5 or V2 3x9 cards. Zero means a blank V2 cell."""
    if len(numbers) == 27:
        rows, cols = 3, 9
    elif len(numbers) != rows * cols:
        return "INVALID_CARD"

    called_set = {int(n) for n in called}
    lines: list[str] = []
    for row in range(rows):
        row_numbers = numbers[row * cols:(row + 1) * cols]
        cells = []
        for raw in row_numbers:
            n = int(raw)
            if n == 0:
                cells.append(" -- ")
            elif n in called_set:
                cells.append(f"[{n:02d}]")
            else:
                cells.append(f" {n:02d} ")
        lines.append(" ".join(cells))
    return "\n".join(lines)
