from __future__ import annotations

from typing import Iterable


from app.utils.bingo_v2 import is_valid_tambola_card
from app.utils.messages import RULE_ERROR, RULE_LINES, stored_rule


def render_card_text(numbers: list[int], called: Iterable[int], game_rule: str, layout: int) -> str:
    rule = stored_rule(game_rule, layout)
    if rule == "UNKNOWN":
        return RULE_ERROR
    if rule == "LEGACY":
        valid = (isinstance(numbers, list) and len(numbers) == 20
                 and all(type(n) is int and 1 <= n <= 90 for n in numbers)
                 and len(set(numbers)) == 20)
        cols = 5
    else:
        valid = is_valid_tambola_card(numbers)
        cols = 9
    if not valid:
        return "اعداد کارت با ساختار ذخیره‌شدهٔ بازی سازگار نیست."
    drawn = set(called)
    lines = []
    hits = []
    for start in range(0, len(numbers), cols):
        row = numbers[start:start + cols]
        hits.append(sum(n != 0 and n in drawn for n in row))
        cells = [" -- " if n == 0 else f"[{n:02d}]" if n in drawn else f" {n:02d} " for n in row]
        lines.append(" ".join(cells))
    lines += [f"تطبیق: {sum(hits)} از {5 * len(hits)}",
              "تطبیق ردیف‌ها از ۵: " + "، ".join(map(str, hits)),
              RULE_LINES[rule].strip().replace("<b>", "").replace("</b>", ""),
              "ثبت برد و پرداخت جایزه جداگانه اعلام می‌شود."]
    return "\n".join(lines)
