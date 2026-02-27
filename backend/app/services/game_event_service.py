from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import select, text

from app.models.game_event import GameEvent


class GameEventService:
    """
    DB schema (game_events):
      - id (AI)
      - game_id (NOT NULL)
      - tg_group_id (NULL)
      - kind (ENUM... per DB)
      - actor_user_id (NULL)
      - idem_key (VARCHAR, UNIQUE)
      - payload_json (JSON, NULL)
      - created_at
    """

    @staticmethod
    def emit(
        db: Session,
        *,
        kind: str,
        game_id: int,
        tg_group_id: int | None = None,
        actor_user_id: int | None = None,
        idem_key: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        # idem_key باید UNIQUE باشد (تو DB هم uq گذاشتی)
        if not idem_key:
            idem_key = f"{kind}:{int(game_id)}"

        payload_json: str | None = None
        if payload is not None:
            payload_json = json.dumps(payload, ensure_ascii=False)

        stmt = text("""
            INSERT INTO game_events
              (game_id, tg_group_id, kind, actor_user_id, idem_key, payload_json)
            VALUES
              (
                :game_id,
                :tg_group_id,
                :kind,
                :actor_user_id,
                :idem_key,
                CASE
                  WHEN :payload_json IS NULL THEN NULL
                  ELSE CAST(:payload_json AS JSON)
                END
              )
            ON DUPLICATE KEY UPDATE
              idem_key = idem_key
        """)

        db.execute(
            stmt,
            {
                "game_id": int(game_id),
                "tg_group_id": int(tg_group_id) if tg_group_id is not None else None,
                "kind": str(kind),
                "actor_user_id": int(actor_user_id) if actor_user_id is not None else None,
                "idem_key": str(idem_key),
                "payload_json": payload_json,
            },
        )

    @staticmethod
    def list_events(db: Session, game_id: int, after_id: int = 0, limit: int = 50):
        q = (
            select(GameEvent)
            .where(GameEvent.game_id == game_id, GameEvent.id > after_id)
            .order_by(GameEvent.id.asc())
            .limit(limit)
        )
        return db.execute(q).scalars().all()