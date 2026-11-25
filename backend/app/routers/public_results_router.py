"""Read-only public prize records for the last five completed games.
No wallet balances, Telegram IDs, addresses or inferred shares are exposed.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.mini_security import get_mini_user_id
from app.models.game import Game, GameCard
from app.models.game_event import GameEvent
from app.models.user import User
from app.utils.messages import stored_rule

router = APIRouter(prefix="/mini-api", tags=["public-results"])

@router.get("/games/recent-results")
def recent_results(response: Response, user_id: int = Depends(get_mini_user_id), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "private, no-store"
    games = db.scalars(select(Game).where(Game.status == "ENDED", Game.ended_at.is_not(None))
                       .order_by(Game.ended_at.desc(), Game.id.desc()).limit(5)).all()
    items = []
    for game in games:
        rule = stored_rule(game.game_rule, game.card_layout_version)
        rows = db.scalars(select(GameEvent).where(GameEvent.game_id == game.id,
                          GameEvent.kind.in_(["PRIZE_COL", "PRIZE_ROW"])).order_by(GameEvent.id.desc())).all()
        winners, seen_kinds, invalid = [], set(), rule == "UNKNOWN"
        for event in rows:
            if event.kind in seen_kinds:
                continue
            seen_kinds.add(event.kind)
            payload = event.payload_json if isinstance(event.payload_json, dict) else {}
            if rule == "UNKNOWN" or (event.kind == "PRIZE_COL" and rule == "FULL_CARD") or payload.get("game_rule", rule) != rule:
                invalid = True
                continue
            payout = game.payout_state_json if isinstance(game.payout_state_json, dict) else {}
            if event.kind == "PRIZE_COL" and isinstance(payout.get("col"), dict) and payout["col"].get("absorbed_into_row"):
                continue
            cards, users, amounts = (payload.get(k) for k in ("winner_card_ids", "winner_user_ids", "amounts_by_card"))
            if not isinstance(cards, list) or not isinstance(users, list) or len(cards) != len(users):
                invalid = True
                continue
            seen_cards = set()
            for index, cid in enumerate(cards):
                uid = users[index]
                if type(cid) is not int or type(uid) is not int or cid in seen_cards:
                    invalid = True
                    continue
                seen_cards.add(cid)
                card = db.get(GameCard, cid)
                if not card or card.game_id != game.id or card.user_id != uid:
                    invalid = True
                    continue
                user = db.get(User, uid)
                name = str(getattr(user, "username", None) or getattr(user, "first_name", None) or "").strip()
                alias = (name[:2] + "•••") if name else "•••"
                amount = amounts[index] if isinstance(amounts, list) and index < len(amounts) else None
                if type(amount) is not int or amount < 0:
                    amount = None
                winners.append(dict(alias=alias, card=card.display_serial or card.id, kind=event.kind,
                                    amount=amount, event_id=event.id))
        items.append(dict(game_id=game.id, code=game.display_code or str(game.id), game_rule=rule,
                          card_layout_version=game.card_layout_version, ended_at=game.ended_at,
                          winners=winners, incomplete=invalid))
    return dict(items=items, fetched_at=datetime.now(timezone.utc))
