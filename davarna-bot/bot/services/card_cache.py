from __future__ import annotations
from typing import Any

# key: (tg_user_id, card_id) -> card dict
_CARD_CACHE: dict[tuple[int, int], dict[str, Any]] = {}

def put_card(tg_user_id: int, card: dict) -> None:
    cid = int(card.get("id"))
    _CARD_CACHE[(tg_user_id, cid)] = card

def get_card(tg_user_id: int, card_id: int) -> dict | None:
    return _CARD_CACHE.get((tg_user_id, int(card_id)))
