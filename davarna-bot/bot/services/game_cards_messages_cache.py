from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

@dataclass
class CardMsgRef:
    card_id: int
    message_id: int

# key: (tg_user_id, game_id) -> list of message refs
_GAME_CARD_MSGS: Dict[Tuple[int, int], List[CardMsgRef]] = {}

def set_game_card_messages(tg_user_id: int, game_id: int, refs: List[CardMsgRef]) -> None:
    _GAME_CARD_MSGS[(tg_user_id, game_id)] = refs

def get_game_card_messages(tg_user_id: int, game_id: int) -> List[CardMsgRef]:
    return _GAME_CARD_MSGS.get((tg_user_id, game_id), [])
