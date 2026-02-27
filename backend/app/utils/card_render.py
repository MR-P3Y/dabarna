from __future__ import annotations
from typing import Iterable

def render_card_text(numbers: list[int], called: Iterable[int], rows: int = 4, cols: int = 5) -> str:
    called_set = set(int(x) for x in called)
    if len(numbers) != rows * cols:
        return "INVALID_CARD"

    lines = []
    for r in range(rows):
        row = numbers[r*cols:(r+1)*cols]
        cells = []
        for n in row:
            if n in called_set:
                # هایلایت ساده
                cells.append(f"[{n:02d}]")
            else:
                cells.append(f" {n:02d} ")
        lines.append(" ".join(cells))
    return "\n".join(lines)
