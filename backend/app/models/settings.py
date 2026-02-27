import os
from sqlalchemy import String, JSON, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

class AppSetting(Base):
    __tablename__ = "app_settings"

    k: Mapped[str] = mapped_column(String(64), primary_key=True)
    v_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    updated_at: Mapped[str] = mapped_column(
        TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"), nullable=False
    )
