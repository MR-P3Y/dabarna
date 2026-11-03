from sqlalchemy import BigInteger, DECIMAL, Integer, String, TIMESTAMP, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class GameAutopilotConfig(Base):
    __tablename__ = "game_autopilot_configs"

    level: Mapped[str] = mapped_column(String(16), primary_key=True)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    scheduler_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="MANUAL")
    start_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="MANUAL")
    draw_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="MANUAL")

    card_price: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    commission_rate: Mapped[str] = mapped_column(DECIMAL(5, 4), nullable=False, server_default="0.1000")

    announce_before_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="300")
    countdown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    repeat_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="600")
    draw_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10")
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")

    # Business rule: a game is never allowed to run with only one distinct player.
    min_unique_players: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")

    updated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    updated_at: Mapped[str] = mapped_column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
