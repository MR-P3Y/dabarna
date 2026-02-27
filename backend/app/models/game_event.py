from __future__ import annotations

from sqlalchemy import Column, BigInteger, Enum, JSON, String, TIMESTAMP, text, ForeignKey
from app.core.db import Base

class GameEvent(Base):
    __tablename__ = "game_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    game_id = Column(BigInteger, ForeignKey("games.id"), nullable=False)
    tg_group_id = Column(BigInteger, nullable=True)

    kind = Column(
        Enum(
            "GAME_CREATED",
            "CARDS_PURCHASED",
            "GAME_STARTED",
            "GAME_START_REJECTED",
            "NUMBER_CALLED",
            "NUMBER_UNDONE",
            "PRIZE_COL",
            "PRIZE_ROW",
            "GAME_ENDED",
            "GAME_LOBBY_CLOSED",
            "ERROR",
            name="game_event_kind",
        ),
        nullable=False,
    )

    actor_user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    idem_key = Column(String(120), nullable=True)
    payload_json = Column(JSON, nullable=True)

    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
