from sqlalchemy import (
    BigInteger, Integer, String, TIMESTAMP, text, ForeignKey,
    Enum, DECIMAL, JSON, UniqueConstraint, Index
)
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

GameStatus = Enum("LOBBY","RUNNING","ENDED", name="game_status")

class Game(Base):
    __tablename__ = "games"
    __table_args__ = (
        Index("idx_group_status", "tg_group_id", "status"),
        Index("idx_group_topic_status", "tg_group_id", "tg_topic_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tg_group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tg_topic_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    status: Mapped[str] = mapped_column(GameStatus, nullable=False, server_default="LOBBY")
    admin_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)

    card_price: Mapped[int] = mapped_column(BigInteger, nullable=False)

    sold_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    commission_rate: Mapped[str] = mapped_column(DECIMAL(5,4), nullable=False, server_default="0.1000")
    commission_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    prize_pool: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")

    col_prize_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    row_prize_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")

    prize_locked: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    started_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    ended_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)

    col_paid: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    payout_state_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    row_winner_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)

    created_at: Mapped[str] = mapped_column(
        TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

class GamePurchase(Base):
    __tablename__ = "game_purchases"
    __table_args__ = (Index("idx_game_user", "game_id", "user_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("games.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)

    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_price: Mapped[int] = mapped_column(BigInteger, nullable=False)

    wallet_tx_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("wallet_txs.id"), nullable=False)

    created_at: Mapped[str] = mapped_column(
        TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

class GameCard(Base):
    __tablename__ = "game_cards"
    __table_args__ = (
        UniqueConstraint("game_id", "fingerprint", name="uq_game_cards_game_fp"),
        Index("idx_game_user", "game_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("games.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    purchase_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("game_purchases.id"), nullable=False)

    numbers_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[str] = mapped_column(
        TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

class GameCalledNumber(Base):
    __tablename__ = "game_called_numbers"
    __table_args__ = (UniqueConstraint("game_id", "number", name="uq_game_number"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("games.id"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)

    called_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
