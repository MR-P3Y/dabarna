from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel

class GameEventOut(BaseModel):
    id: int
    game_id: int
    kind: str
    actor_user_id: Optional[int] = None
    payload: Optional[Any] = None
    created_at: str  # ساده نگه می‌داریم؛ بعداً می‌تونیم datetime کنیم
