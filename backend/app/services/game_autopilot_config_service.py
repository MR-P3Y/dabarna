from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import (
    USER_TOPIC_GAME_HIGH_ID,
    USER_TOPIC_GAME_LOW_ID,
    USER_TOPIC_GAME_MEDIUM_ID,
)
from app.models.game_autopilot import GameAutopilotConfig


AUTOPILOT_LEVELS = ("LOW", "MEDIUM", "HIGH")
AUTOPILOT_MODES = {"AUTO", "MANUAL"}
DEFAULT_COMMISSION_RATE = Decimal("0.1000")


def _normalize_level(level: str | None) -> str | None:
    raw = str(level or "").strip().upper()
    if not raw:
        return None
    if raw not in AUTOPILOT_LEVELS:
        raise HTTPException(status_code=400, detail="invalid game level")
    return raw


def _normalize_mode(value: str | None, field: str) -> str:
    raw = str(value or "").strip().upper()
    if raw not in AUTOPILOT_MODES:
        raise HTTPException(status_code=400, detail=f"{field} must be AUTO or MANUAL")
    return raw


def _normalize_commission_rate(value: Any) -> Decimal:
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(status_code=400, detail="invalid commission_rate")
    if rate < Decimal("0") or rate >= Decimal("1"):
        raise HTTPException(status_code=400, detail="commission_rate must be between 0 and 1")
    return rate.quantize(Decimal("0.0001"))


def _positive_int(value: Any, field: str, *, minimum: int = 1, maximum: int = 86400) -> int:
    try:
        out = int(value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"invalid {field}")
    if out < minimum or out > maximum:
        raise HTTPException(status_code=400, detail=f"{field} must be {minimum}..{maximum}")
    return out


class GameAutopilotConfigService:
    @staticmethod
    def normalize_level(level: str | None) -> str | None:
        return _normalize_level(level)

    @staticmethod
    def topic_id_for_level(level: str | None) -> int | None:
        normalized = _normalize_level(level)
        mapping = {
            "LOW": USER_TOPIC_GAME_LOW_ID,
            "MEDIUM": USER_TOPIC_GAME_MEDIUM_ID,
            "HIGH": USER_TOPIC_GAME_HIGH_ID,
        }
        value = mapping.get(normalized) if normalized else None
        return int(value) if value is not None else None

    @staticmethod
    def level_for_topic(tg_topic_id: int | None) -> str | None:
        if tg_topic_id is None:
            return None
        topic = int(tg_topic_id)
        mapping = {
            int(USER_TOPIC_GAME_LOW_ID): "LOW" if USER_TOPIC_GAME_LOW_ID is not None else None,
            int(USER_TOPIC_GAME_MEDIUM_ID): "MEDIUM" if USER_TOPIC_GAME_MEDIUM_ID is not None else None,
            int(USER_TOPIC_GAME_HIGH_ID): "HIGH" if USER_TOPIC_GAME_HIGH_ID is not None else None,
        }
        return mapping.get(topic)

    @staticmethod
    def get(db: Session, level: str) -> GameAutopilotConfig:
        normalized = _normalize_level(level)
        row = db.get(GameAutopilotConfig, normalized)
        if row is None:
            raise HTTPException(status_code=404, detail="autopilot config not found")
        return row

    @staticmethod
    def list(db: Session) -> list[GameAutopilotConfig]:
        rows = db.execute(
            select(GameAutopilotConfig).order_by(GameAutopilotConfig.level.asc())
        ).scalars().all()
        by_level = {str(row.level).upper(): row for row in rows}
        return [by_level[level] for level in AUTOPILOT_LEVELS if level in by_level]

    @staticmethod
    def serialize(row: GameAutopilotConfig) -> dict[str, Any]:
        return {
            "level": str(row.level).upper(),
            "enabled": bool(int(row.enabled or 0)),
            "scheduler_mode": str(row.scheduler_mode or "MANUAL").upper(),
            "start_mode": str(row.start_mode or "MANUAL").upper(),
            "draw_mode": str(row.draw_mode or "MANUAL").upper(),
            "card_price": int(row.card_price) if row.card_price is not None else None,
            "commission_rate": float(Decimal(str(row.commission_rate or DEFAULT_COMMISSION_RATE))),
            "announce_before_seconds": int(row.announce_before_seconds),
            "countdown_seconds": int(row.countdown_seconds),
            "repeat_interval_seconds": int(row.repeat_interval_seconds),
            "draw_interval_seconds": int(row.draw_interval_seconds),
            "cooldown_seconds": int(row.cooldown_seconds),
            "min_unique_players": int(row.min_unique_players),
            "topic_id": GameAutopilotConfigService.topic_id_for_level(str(row.level)),
            "updated_by": int(row.updated_by) if row.updated_by is not None else None,
            "updated_at": str(row.updated_at) if row.updated_at is not None else None,
        }

    @staticmethod
    def commission_rate_for_level(db: Session, level: str | None) -> Decimal:
        normalized = _normalize_level(level)
        if not normalized:
            return DEFAULT_COMMISSION_RATE
        row = db.get(GameAutopilotConfig, normalized)
        if row is None:
            return DEFAULT_COMMISSION_RATE
        return _normalize_commission_rate(row.commission_rate)

    @staticmethod
    def configured_card_price(db: Session, level: str | None) -> int | None:
        normalized = _normalize_level(level)
        if not normalized:
            return None
        row = db.get(GameAutopilotConfig, normalized)
        if row is None or row.card_price is None:
            return None
        return int(row.card_price)

    @staticmethod
    def update(
        db: Session,
        *,
        level: str,
        values: dict[str, Any],
        updated_by: int | None,
        allow_commission_change: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        row = GameAutopilotConfigService.get(db, level)
        before = GameAutopilotConfigService.serialize(row)

        if "enabled" in values and values["enabled"] is not None:
            row.enabled = 1 if bool(values["enabled"]) else 0

        for field in ("scheduler_mode", "start_mode", "draw_mode"):
            if field in values and values[field] is not None:
                setattr(row, field, _normalize_mode(values[field], field))

        if "card_price" in values and values["card_price"] is not None:
            row.card_price = _positive_int(values["card_price"], "card_price", minimum=1000, maximum=10_000_000_000)

        if "commission_rate" in values and values["commission_rate"] is not None:
            if not allow_commission_change:
                raise HTTPException(status_code=403, detail="commission can only be changed by super admin")
            row.commission_rate = _normalize_commission_rate(values["commission_rate"])

        numeric_rules = {
            "announce_before_seconds": (10, 86400),
            "countdown_seconds": (5, 600),
            "repeat_interval_seconds": (60, 86400),
            "draw_interval_seconds": (2, 300),
            "cooldown_seconds": (0, 3600),
        }
        for field, (minimum, maximum) in numeric_rules.items():
            if field in values and values[field] is not None:
                setattr(row, field, _positive_int(values[field], field, minimum=minimum, maximum=maximum))

        # v1 business rule is intentionally fixed. It is stored in DB for observability,
        # but no admin endpoint can reduce it below two distinct players.
        row.min_unique_players = 2
        row.updated_by = int(updated_by) if updated_by is not None else None

        db.flush()
        after = GameAutopilotConfigService.serialize(row)
        return before, after
