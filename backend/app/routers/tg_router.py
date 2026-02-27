from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query # type: ignore
from sqlalchemy import select # type: ignore
from sqlalchemy.orm import Session # type: ignore
import json

from app.core.db import get_db
from app.core.admin_guard import require_admin_any, AdminIdentity
from app.models.game import Game
from app.schemas.game import CreateGameIn, GameOut, StartGameIn, CallNumberIn, CallNumberOut, GameStateOut
from app.services.game_service import GameService

router = APIRouter(prefix="/tg", tags=["tg"])


def _admin_user_id(ident: AdminIdentity) -> int:
    if ident.user_id is None:
        raise HTTPException(status_code=403, detail="forbidden")
    return ident.user_id


def _get_active_game(db: Session, tg_group_id: int, tg_topic_id: int | None = None) -> Game | None:
    # فعال یعنی LOBBY یا RUNNING
    q = (
        select(Game)
        .where(
            Game.tg_group_id == tg_group_id,
            Game.status.in_(["LOBBY", "RUNNING"]),
        )
        .order_by(Game.id.desc())
        .limit(1)
    )
    if tg_topic_id is not None:
        q = q.where(Game.tg_topic_id == int(tg_topic_id))
    return db.execute(q).scalar_one_or_none()


def _row_paid_from_game(g: Game) -> int:
    raw = g.payout_state_json
    if isinstance(raw, dict):
        try:
            return int(raw.get("row_paid", 0) or 0)
        except Exception:
            return 0
    if isinstance(raw, str):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return int(obj.get("row_paid", 0) or 0)
        except Exception:
            return 0
    return 0


def _to_game_out(g: Game) -> GameOut:
    return GameOut(
        id=g.id,
        tg_group_id=g.tg_group_id,
        tg_topic_id=g.tg_topic_id,
        status=g.status,
        admin_user_id=g.admin_user_id,
        card_price=g.card_price,
        sold_amount=g.sold_amount,
        commission_amount=g.commission_amount,
        prize_pool=g.prize_pool,
        prize_locked=g.prize_locked,
        col_prize_amount=g.col_prize_amount,
        row_prize_amount=g.row_prize_amount,
        col_paid=int(g.col_paid),
        row_paid=_row_paid_from_game(g),
    )


@router.get("/groups/{tg_group_id}/active-game", response_model=GameOut)
def active_game(
    tg_group_id: int,
    tg_topic_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    g = _get_active_game(db, tg_group_id, tg_topic_id=tg_topic_id)
    if not g:
        raise HTTPException(status_code=404, detail="no active game")
    return _to_game_out(g)


@router.post("/groups/{tg_group_id}/games/ensure-active", response_model=GameOut)
def ensure_active_game(
    tg_group_id: int,
    payload: CreateGameIn,
    tg_topic_id: int | None = Query(default=None),
    ident: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    # payload باید شامل tg_group_id و card_price باشد؛ ولی برای جلوگیری از اشتباه،
    # tg_group_id را از path تحمیل می‌کنیم.
    if payload.tg_group_id is not None and payload.tg_group_id != tg_group_id:
        raise HTTPException(status_code=400, detail="tg_group_id mismatch")
    if tg_topic_id is not None and payload.tg_topic_id is not None and int(payload.tg_topic_id) != int(tg_topic_id):
        raise HTTPException(status_code=400, detail="tg_topic_id mismatch")

    resolved_topic_id = (
        int(tg_topic_id)
        if tg_topic_id is not None
        else (int(payload.tg_topic_id) if payload.tg_topic_id is not None else None)
    )

    g = _get_active_game(db, tg_group_id, tg_topic_id=resolved_topic_id)
    if g:
        return _to_game_out(g)

    admin_uid = _admin_user_id(ident)
    new_g = GameService.create_game(
        db,
        admin_user_id=admin_uid,
        tg_group_id=tg_group_id,
        tg_topic_id=resolved_topic_id,
        card_price=payload.card_price,
    )
    db.commit()

    return _to_game_out(new_g)


@router.post("/groups/{tg_group_id}/start", response_model=GameOut)
def start_active_game(
    tg_group_id: int,
    payload: StartGameIn,
    tg_topic_id: int | None = Query(default=None),
    ident: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    g = _get_active_game(db, tg_group_id, tg_topic_id=tg_topic_id)
    if not g:
        raise HTTPException(status_code=404, detail="no active game")

    admin_uid = _admin_user_id(ident)
    updated = GameService.start_game(db=db, game_id=g.id, admin_user_id=admin_uid, idempotency_key=payload.idempotency_key)
    db.commit()

    return _to_game_out(updated)


@router.post("/groups/{tg_group_id}/call", response_model=CallNumberOut)
def call_number_on_active_game(
    tg_group_id: int,
    payload: CallNumberIn,
    tg_topic_id: int | None = Query(default=None),
    ident: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    g = _get_active_game(db, tg_group_id, tg_topic_id=tg_topic_id)
    if not g:
        raise HTTPException(status_code=404, detail="no active game")

    admin_uid = _admin_user_id(ident)
    res = GameService.call_number(
        db=db,
        game_id=g.id,
        number=payload.number,
        admin_user_id=admin_uid,
        idempotency_key=payload.idempotency_key,
    )
    db.commit()
    return CallNumberOut(**res)


@router.get("/groups/{tg_group_id}/state", response_model=GameStateOut)
def state_of_active_game(
    tg_group_id: int,
    last_n: int = 12,
    tg_topic_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    g = _get_active_game(db, tg_group_id, tg_topic_id=tg_topic_id)
    if not g:
        raise HTTPException(status_code=404, detail="no active game")
    s = GameService.get_state(db, game_id=g.id, last_n=last_n)
    return GameStateOut(**s)
