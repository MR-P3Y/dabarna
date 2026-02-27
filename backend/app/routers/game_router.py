from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import select
import json
from app.core.db import get_db
from app.core.config import DEFAULT_TG_GROUP_ID
from app.core.user_guard import get_current_user_id
from app.core.admin_guard import require_admin_any, AdminIdentity
from app.models.game import Game
from app.schemas.game import (
    CreateGameIn, GameOut, BuyCardsIn, BuyCardsOut, GameStateOut, StartGameIn,
    CallNumberIn, CallNumberOut, MyCardsOut, CardOut, MyCardsPreviewOut, CardPreviewOut,
    GroupMessageOut,TgMessageOut
)
from app.services.game_service import GameService, GameEventService
from app.utils.card_render import render_card_text
from app.utils.messages import format_game_lobby, format_game_running, format_row_winner, format_col_winner
from app.utils.game_messages import build_private_cards_blocks, group_message_running, private_cards_preview
from app.schemas.game_events import GameEventOut
from app.utils.tg_text import chunk_text, paginate_blocks



router = APIRouter(prefix="/games", tags=["games"])



def _admin_user_id(ident: AdminIdentity) -> int:
    # در گارد تضمین شده، ولی برای حالت AUTH_DISABLED ممکنه None باشد
    if ident.user_id is None:
        raise HTTPException(status_code=403, detail="forbidden")
    return ident.user_id


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



@router.post("", response_model=GameOut)
def create_game(
    payload: CreateGameIn,
    ident: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    tg_group_id = payload.tg_group_id if payload.tg_group_id is not None else DEFAULT_TG_GROUP_ID
    if tg_group_id is None:
        raise HTTPException(
            status_code=400,
            detail="tg_group_id is required (set it in payload or DEFAULT_TG_GROUP_ID in .env)",
        )

    admin_uid = _admin_user_id(ident)
    g = GameService.create_game(
        db,
        admin_user_id=admin_uid,
        tg_group_id=tg_group_id,
        tg_topic_id=payload.tg_topic_id,
        card_price=payload.card_price,
    )
    db.commit()
    return _to_game_out(g)

@router.get("/{game_id}", response_model=GameOut)
def get_game(game_id: int, db: Session = Depends(get_db)):
    g = db.execute(select(Game).where(Game.id == game_id)).scalar_one()
    return _to_game_out(g)

@router.post("/{game_id}/buy", response_model=BuyCardsOut)
def buy_cards(
    game_id: int,
    payload: BuyCardsIn,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    purchase, cards, prize_pool = GameService.buy_cards(
        db=db, game_id=game_id, user_id=current_user_id, qty=payload.qty, idempotency_key=payload.idempotency_key
    )
    db.commit()
    return BuyCardsOut(
        game_id=game_id,
        purchase_id=purchase.id,
        qty=purchase.qty,
        total_price=purchase.total_price,
        wallet_tx_id=purchase.wallet_tx_id,
        prize_pool=prize_pool,
    )

@router.post("/{game_id}/start", response_model=GameOut)
def start_game(
    game_id: int,
    payload: StartGameIn,
    ident: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    admin_uid = _admin_user_id(ident)
    g = GameService.start_game(db=db, game_id=game_id, admin_user_id=admin_uid, idempotency_key=payload.idempotency_key)
    db.commit()
    return _to_game_out(g)

@router.post("/{game_id}/call", response_model=CallNumberOut)
def call_number(
    game_id: int,
    payload: CallNumberIn,
    ident: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    admin_uid = _admin_user_id(ident)
    res = GameService.call_number(
        db=db, game_id=game_id, number=payload.number, admin_user_id=admin_uid, idempotency_key=payload.idempotency_key
    )
    db.commit()
    return CallNumberOut(**res)



@router.get("/{game_id}/my-cards", response_model=MyCardsOut)
def my_cards(
    game_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    cards = GameService.get_user_cards(db, game_id=game_id, user_id=current_user_id)
    return MyCardsOut(
        game_id=game_id,
        cards=[CardOut(**c) for c in cards],
    )

@router.get("/{game_id}/state", response_model=GameStateOut)
def game_state(game_id: int, last_n: int = 12, db: Session = Depends(get_db)):
    s = GameService.get_state(db, game_id=game_id, last_n=last_n)
    return GameStateOut(**s)


@router.get("/{game_id}/my-cards/preview", response_model=MyCardsPreviewOut)
def my_cards_preview(
    game_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    cards = GameService.get_user_cards(db, game_id=game_id, user_id=current_user_id)
    state = GameService.get_state(db, game_id=game_id, last_n=200)
    called = state["called_numbers"]

    previews: list[CardPreviewOut] = []
    for c in cards:
        grid = render_card_text(c["numbers"], called)
        previews.append(
            CardPreviewOut(
                card_id=c["card_id"],
                fingerprint=c["fingerprint"],
                grid_text=grid,
            )
        )

    # حتی اگر کارت نداشت، باز هم خروجی معتبر بده
    return MyCardsPreviewOut(
        game_id=game_id,
        called_numbers=called,
        cards=previews,
    )


@router.get("/{game_id}/group-message", response_model=GroupMessageOut)
def group_message(game_id: int, db: Session = Depends(get_db)):
    state = GameService.get_state(db, game_id=game_id, last_n=12)

    if state["status"] == "LOBBY":
        text = format_game_lobby(state)
        mode = "LOBBY"
    elif state["status"] == "RUNNING":
        # پیام running + اگر بردی ثبت شده باشد اضافه می‌کنیم
        parts = [format_game_running(state)]
        lw = format_col_winner(state)
        if lw:
            parts.append("\n" + lw)
        fw = format_row_winner(state)
        if fw:
            parts.append("\n" + fw)
        text = "\n".join(parts)
        mode = "RUNNING"
    else:
        parts = [format_game_running(state)]
        fw = format_row_winner(state)
        if fw:
            parts.append("\n" + fw)
        text = "\n".join(parts)
        mode = "ENDED"

    return GroupMessageOut(game_id=game_id, mode=mode, text=text)

@router.get("/{game_id}/group-message/plain", response_model=TgMessageOut)
def group_message(game_id: int, db: Session = Depends(get_db)):
    st = GameService.get_state(db, game_id, last_n=24)
    if st["status"] == "RUNNING":
        txt = group_message_running(
            game_id=st["game_id"],
            card_price=st["card_price"],
            prize_pool=st["prize_pool"],
            col_prize_amount=st["col_prize_amount"],
            row_prize_amount=st["row_prize_amount"],
            called_numbers=st["called_numbers"],
            last_number=st["last_number"],
        )
        return TgMessageOut(game_id=game_id, mode="RUNNING", parse_mode="MarkdownV2", text=txt)

    # برای LOBBY/ENDED بعداً متن جدا می‌سازیم
    return TgMessageOut(game_id=game_id, mode=st["status"], parse_mode="MarkdownV2", text="")


@router.get("/{game_id}/my-cards/message", response_model=TgMessageOut)
def my_cards_message(
    game_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    pv = GameService.get_user_cards_preview(db, game_id, current_user_id)

    header_block, card_blocks = build_private_cards_blocks(
        game_id=pv["game_id"],
        user_id=pv["user_id"],
        called_numbers=pv["called_numbers"],
        cards=pv["cards"],
    )

    parts = paginate_blocks(header_block, card_blocks)

    return TgMessageOut(
        game_id=game_id,
        mode="PRIVATE_CARDS",
        parse_mode="MarkdownV2",
        text=parts[0] if parts else "",
        parts=parts if len(parts) > 1 else None,  # یا همیشه بده؛ انتخاب تو
    )


@router.get("/{game_id}/events", response_model=list[GameEventOut])
def list_game_events(game_id: int, after_id: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    rows = GameEventService.list_events(db, game_id=game_id, after_id=after_id, limit=min(limit, 200))
    return [
        GameEventOut(
            id=int(r.id),
            game_id=int(r.game_id),
            kind=str(r.kind),
            actor_user_id=int(r.actor_user_id) if r.actor_user_id else None,
            payload=r.payload_json,
            created_at=str(r.created_at),
        )
        for r in rows
    ]
