from __future__ import annotations

from typing import Iterable
from app.utils.tg_markdown import md2_escape


def build_private_cards_blocks(game_id: int, user_id: int, called_numbers: Iterable[int],
                               cards: list[dict]) -> tuple[str, list[str]]:
    called = "، ".join(map(str, called_numbers)) or "هنوز ثبت نشده"
    header = md2_escape(f"کارت‌های من | بازی شماره {game_id}\nاعداد اعلام‌شده: {called}")
    blocks = []
    for card in cards:
        grid = str(card["grid_text"]).replace("\\", "\\\\").replace("`", "\\`")
        blocks.append(f"کارت شماره {int(card['card_id'])}\n```\n{grid}\n```")
    return header, blocks or ["هنوز کارتی برای این بازی ثبت نشده است"]
