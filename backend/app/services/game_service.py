from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.redis_client import RedisLock, idem_get, idem_set
from app.models.game import Game, GameCalledNumber, GameCard, GamePurchase
from app.models.user import User
from app.models.settings import AppSetting
from sqlalchemy.exc import IntegrityError as SAIntegrityError
from app.services.game_event_service import GameEventService
from app.services.wallet_service import WalletService
from app.utils.bingo import (
    card_fingerprint,
    check_line,
    generate_card_numbers,
)


def _round_int(x: Decimal) -> int:
    return int(x.to_integral_value(rounding=ROUND_HALF_UP))


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


class GameService:
    # ---- settings keys ----
    KEY_MAX_CARDS = "max_cards_per_purchase"
    KEY_MAX_NUMBER = "max_number"

    # ---- final executable rule (fixed percentages) ----
    # Commission is 10% of sold_amount. prize_pool = sold_amount - commission_amount (90% of sold).
    # Column is 30% of sold, Row is 60% of sold. As a share of prize_pool (90%), that is 1/3 and 2/3.
    COMMISSION_RATE = Decimal("0.10")
    COL_PRIZE_SHARE_OF_POOL = Decimal("1") / Decimal("3")
    ROW_PRIZE_SHARE_OF_POOL = Decimal("2") / Decimal("3")

    @staticmethod
    def _get_setting(db: Session, key: str, default):
        s = db.get(AppSetting, key)
        if not s:
            return default
        return s.v_json

    @staticmethod
    def _split_equal(total_amount: int, winners_count: int) -> list[int]:
        if winners_count <= 0:
            return []
        base = int(total_amount) // int(winners_count)
        remainder = int(total_amount) - (base * int(winners_count))
        return [base + (1 if i < remainder else 0) for i in range(int(winners_count))]

    @staticmethod
    def _load_payout_state(raw: Any) -> dict:
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return dict(raw)
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return {}
            try:
                obj = json.loads(s)
                return obj if isinstance(obj, dict) else {}
            except Exception:
                return {}
        return {}

    @staticmethod
    def _winner_cards(cards: list[GameCard], called_set: set[int], mode: str) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for c in cards:
            nums = c.numbers_json
            if isinstance(nums, str):
                nums = json.loads(nums)
            if check_line(nums, called_set, mode=mode):
                out.append((int(c.id), int(c.user_id)))
        out.sort(key=lambda x: x[0])  # deterministic
        return out

    @staticmethod
    def _as_int_list(values: Any) -> list[int]:
        if not isinstance(values, list):
            return []
        out: list[int] = []
        for v in values:
            try:
                out.append(int(v))
            except Exception:
                continue
        return out

    @staticmethod
    def create_game(
        db: Session,
        admin_user_id: int,
        tg_group_id: int,
        tg_topic_id: int | None,
        card_price: int,
    ) -> Game:
        if card_price <= 0:
            raise HTTPException(status_code=400, detail="card_price must be > 0")

        g = Game(
            tg_group_id=tg_group_id,
            tg_topic_id=tg_topic_id,
            admin_user_id=admin_user_id,
            card_price=card_price,
            status="LOBBY",
        )
        db.add(g)
        db.flush()

        # Event (idempotent-ish)
        try:
            GameEventService.emit(
                db,
                kind="GAME_CREATED",
                game_id=int(g.id),
                tg_group_id=int(g.tg_group_id),
                actor_user_id=int(admin_user_id),
                idem_key=f"GAME_CREATED:{g.id}",
                payload={
                    "card_price": int(card_price),
                    "tg_topic_id": int(tg_topic_id) if tg_topic_id is not None else None,
                },
            )


        except Exception:
            # نباید بازی را fail کند
            pass

        return g

    @staticmethod
    def buy_cards(
        db: Session,
        game_id: int,
        user_id: int,
        qty: int,
        idempotency_key: str,
    ) -> tuple[GamePurchase, list[GameCard], int]:
        max_cards = int(GameService._get_setting(db, GameService.KEY_MAX_CARDS, 50))
        if qty < 1 or qty > max_cards:
            raise HTTPException(status_code=400, detail=f"qty must be 1..{max_cards}")

        # lock game row
        game = (
            db.execute(select(Game).where(Game.id == game_id).with_for_update())
            .scalar_one_or_none()
        )
        if not game:
            raise HTTPException(status_code=404, detail="game not found")
        if str(game.status) != "LOBBY":
            raise HTTPException(status_code=400, detail="game is not in LOBBY")
        if _safe_int(game.prize_locked) == 1:
            raise HTTPException(status_code=400, detail="prize locked")

        unit_price = int(game.card_price)
        total_price = unit_price * int(qty)

        # debit wallet (idempotent inside WalletService)
        tx = WalletService.debit(
            db=db,
            user_id=int(user_id),
            amount=int(total_price),
            reason="BUY_CARDS",
            idempotency_key=str(idempotency_key),
            ref_type="GAME",
            ref_id=int(game.id),
        )

        # If tx existed before -> return existing purchase & cards
        existing_purchase = (
            db.execute(
                select(GamePurchase)
                .where(GamePurchase.wallet_tx_id == tx.id)
                .with_for_update()
            )
            .scalar_one_or_none()
        )
        if existing_purchase:
            existing_cards = (
                db.execute(select(GameCard).where(GameCard.purchase_id == existing_purchase.id))
                .scalars()
                .all()
            )
            return existing_purchase, existing_cards, int(game.prize_pool)

        purchase = GamePurchase(
            game_id=int(game.id),
            user_id=int(user_id),
            qty=int(qty),
            unit_price=int(unit_price),
            total_price=int(total_price),
            wallet_tx_id=int(tx.id),
        )
        db.add(purchase)
        db.flush()

        # build cards with UNIQUE(game_id,fingerprint) retry (SAFE: SAVEPOINT per card)
        # build cards with UNIQUE(game_id,fingerprint) retry (SAFE: SAVEPOINT per card)
        max_number = int(GameService._get_setting(db, GameService.KEY_MAX_NUMBER, 99))
        cards: list[GameCard] = []

        MAX_RETRY = 5  # ✅ طبق requirement

        for i in range(int(qty)):
            created = False

            for attempt in range(MAX_RETRY):
                seed = f"game:{game.id}|user:{user_id}|purchase:{purchase.id}|i:{i}|a:{attempt}"
                nums = generate_card_numbers(seed=seed, max_number=max_number, count=20)
                fp = card_fingerprint(nums)

                try:
                    with db.begin_nested():
                        c = GameCard(
                            game_id=int(game.id),
                            user_id=int(user_id),
                            purchase_id=int(purchase.id),
                            numbers_json=nums,
                            fingerprint=str(fp),
                        )
                        db.add(c)
                        db.flush()

                    cards.append(c)
                    created = True
                    break

                except SAIntegrityError as e:
                    # ✅ فقط Duplicate Key (MySQL errno=1062) را retry کن
                    code = None
                    try:
                        code = e.orig.args[0]
                    except Exception:
                        pass

                    if code != 1062:
                        raise
                    continue

            if not created:
                raise HTTPException(status_code=500, detail="failed to generate unique card after retries")


        # Final rule: fixed 10% commission
        commission_rate = GameService.COMMISSION_RATE

        sold_new = int(game.sold_amount) + int(total_price)
        commission_new = int(game.commission_amount) + _round_int(Decimal(total_price) * commission_rate)
        prize_pool_new = sold_new - commission_new

        game.sold_amount = int(sold_new)
        game.commission_amount = int(commission_new)
        game.prize_pool = int(prize_pool_new)
        db.flush()

        # Event (idempotent by UNIQUE idem_key)
        try:
            GameEventService.emit(
                db,
                kind="CARDS_PURCHASED",
                game_id=int(game.id),
                tg_group_id=int(game.tg_group_id),
                actor_user_id=int(user_id),
                idem_key=f"CARDS_PURCHASED:{game.id}:{tx.id}",  # stable & unique
                payload={
                    "qty": int(qty),
                    "unit_price": int(unit_price),
                    "total_price": int(total_price),
                    "purchase_id": int(purchase.id),
                    "wallet_tx_id": int(tx.id),
                    "sold_amount": int(game.sold_amount),
                    "commission_amount": int(game.commission_amount),
                    "prize_pool": int(game.prize_pool),
                    "card_ids": [int(c.id) for c in cards],
                    "fingerprints": [str(c.fingerprint) for c in cards],
                },
            )
        except Exception:
            pass

        return purchase, cards, int(prize_pool_new)
    @staticmethod
    def start_game(db: Session, game_id: int, admin_user_id: int, idempotency_key: str) -> Game:
        game = (
            db.execute(select(Game).where(Game.id == game_id).with_for_update())
            .scalar_one_or_none()
        )
        if not game:
            raise HTTPException(status_code=404, detail="game not found")
        if int(game.admin_user_id) != int(admin_user_id):
            raise HTTPException(status_code=403, detail="only game admin can start")

        # ✅ اگر قبلاً شروع شده/قفل شده: فقط state برگردان (هیچ event جدید نزن)
        if str(game.status) != "LOBBY" or _safe_int(game.prize_locked) == 1:
            return game

        if int(game.sold_amount) <= 0:
            # Audit: start rejected (idempotent)
            try:
                GameEventService.emit(
                    db,
                    kind="GAME_START_REJECTED",
                    game_id=int(game.id),
                    tg_group_id=int(game.tg_group_id),
                    actor_user_id=int(admin_user_id),
                    idem_key=f"GAME_START_REJECTED:{game.id}:{idempotency_key}",
                    payload={
                        "reason": "no_cards_sold",
                        "sold_amount": int(game.sold_amount),
                        "status": str(game.status),
                    },
                )
            except Exception:
                pass

            raise HTTPException(status_code=400, detail="cannot start: no cards sold")


        prize_pool = int(game.prize_pool)

        # Final rule:
        # - 30% column prize (paid at most once)
        # - 60% row prize (game-ending prize)
        # We keep exact total by assigning remainder to row.
        col_amount = _round_int(Decimal(prize_pool) * GameService.COL_PRIZE_SHARE_OF_POOL)
        row_amount = int(prize_pool) - int(col_amount)

        game.col_prize_amount = int(col_amount)   # backward-compatible storage for column bucket
        game.row_prize_amount = int(row_amount)   # backward-compatible storage for row bucket
        game.col_paid = 0
        game.payout_state_json = None
        game.row_winner_user_id = None
        game.prize_locked = 1
        game.status = "RUNNING"
        db.flush()

        try:
            GameEventService.emit(
                db,
                kind="GAME_STARTED",
                game_id=int(game.id),
                tg_group_id=int(game.tg_group_id) if getattr(game, "tg_group_id", None) is not None else None,
                actor_user_id=int(admin_user_id),
                idem_key=f"GAME_STARTED:{game.id}:{idempotency_key}",
                payload={
                    "prize_pool": int(game.prize_pool),
                    "col_prize_amount": int(game.col_prize_amount),
                    "row_prize_amount": int(game.row_prize_amount),
                },
            )
        except Exception:
            pass

        return game

    @staticmethod
    def close_lobby_game(
        db: Session,
        game_id: int,
        admin_user_id: int,
        idempotency_key: str,
        cancel_reason: str | None = None,
    ) -> Game:
        game = (
            db.execute(select(Game).where(Game.id == game_id).with_for_update())
            .scalar_one_or_none()
        )
        if not game:
            raise HTTPException(status_code=404, detail="game not found")
        if int(game.admin_user_id) != int(admin_user_id):
            raise HTTPException(status_code=403, detail="only game admin can close lobby game")

        current_status = str(game.status)
        if current_status == "ENDED":
            return game
        if current_status != "LOBBY":
            raise HTTPException(status_code=400, detail="only LOBBY game can be closed")

        called_count = db.execute(
            select(func.count())
            .select_from(GameCalledNumber)
            .where(GameCalledNumber.game_id == int(game.id))
        ).scalar_one()

        if int(called_count) > 0:
            raise HTTPException(status_code=400, detail="cannot close lobby game: numbers already called")

        purchases = (
            db.execute(
                select(GamePurchase)
                .where(GamePurchase.game_id == int(game.id))
                .order_by(GamePurchase.id.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )

        refunds_by_user: dict[int, dict[str, Any]] = {}
        refund_total = 0
        refund_purchases_count = 0

        for p in purchases:
            amount = int(p.total_price or 0)
            if amount <= 0:
                continue

            WalletService.credit(
                db=db,
                user_id=int(p.user_id),
                amount=amount,
                reason="ADJUST",
                idempotency_key=f"LOBBY_REFUND:game:{int(game.id)}:purchase:{int(p.id)}",
                ref_type="GAME",
                ref_id=int(game.id),
            )

            refund_total += amount
            refund_purchases_count += 1

            bucket = refunds_by_user.get(int(p.user_id))
            if not bucket:
                bucket = {
                    "user_id": int(p.user_id),
                    "amount": 0,
                    "purchase_count": 0,
                    "purchase_ids": [],
                }
                refunds_by_user[int(p.user_id)] = bucket

            bucket["amount"] = int(bucket["amount"]) + amount
            bucket["purchase_count"] = int(bucket["purchase_count"]) + 1
            purchase_ids = bucket.get("purchase_ids")
            if isinstance(purchase_ids, list) and len(purchase_ids) < 20:
                purchase_ids.append(int(p.id))

        tg_user_map: dict[int, int] = {}
        if refunds_by_user:
            tg_rows = db.execute(
                select(User.id, User.tg_user_id).where(User.id.in_(list(refunds_by_user.keys())))
            ).all()
            tg_user_map = {
                int(uid): int(tg_uid)
                for uid, tg_uid in tg_rows
                if uid is not None and tg_uid is not None
            }

        refunds_payload: list[dict[str, Any]] = []
        for uid in sorted(refunds_by_user.keys()):
            item = refunds_by_user[uid]
            refunds_payload.append(
                {
                    "user_id": int(item["user_id"]),
                    "tg_user_id": int(tg_user_map.get(int(uid), 0) or 0),
                    "amount": int(item["amount"]),
                    "purchase_count": int(item["purchase_count"]),
                    "purchase_ids": [int(x) for x in (item.get("purchase_ids") or [])],
                }
            )

        cancel_reason_text = str(cancel_reason or "").strip()

        game.sold_amount = 0
        game.commission_amount = 0
        game.prize_pool = 0
        game.col_prize_amount = 0
        game.row_prize_amount = 0
        game.col_paid = 0
        game.prize_locked = 0
        game.payout_state_json = None
        game.row_winner_user_id = None
        game.status = "ENDED"
        db.flush()

        try:
            GameEventService.emit(
                db,
                kind="GAME_LOBBY_CLOSED",
                game_id=int(game.id),
                tg_group_id=int(game.tg_group_id) if getattr(game, "tg_group_id", None) is not None else None,
                actor_user_id=int(admin_user_id),
                idem_key=f"GAME_LOBBY_CLOSED:{game.id}:{idempotency_key}",
                payload={
                    "status_before": "LOBBY",
                    "status_after": "ENDED",
                    "reason": "manual_admin_close",
                    "cancel_reason": cancel_reason_text,
                    "refund_total": int(refund_total),
                    "refund_users_count": len(refunds_payload),
                    "refund_purchases_count": int(refund_purchases_count),
                    "refunds": refunds_payload,
                },
            )
        except Exception:
            pass

        return game



    @staticmethod
    def call_number(
        db: Session,
        game_id: int,
        number: int,
        admin_user_id: int,
        idempotency_key: str,
    ) -> dict:
        # ---- Redis idempotency ----
        idem_cache_key = f"idem:call:{game_id}:{admin_user_id}:{idempotency_key}"
        try:
            cached = idem_get(idem_cache_key)
        except Exception:
            cached = None
        if cached:
            return cached

        # ---- Redis lock ----
        lock = RedisLock(f"game:{game_id}:call_lock", ttl_ms=8000)
        if not lock.acquire():
            raise HTTPException(status_code=409, detail="call locked, try again")

        try:
            # lock game row
            game = (
                db.execute(select(Game).where(Game.id == game_id).with_for_update())
                .scalar_one_or_none()
            )

            if not game:
                raise HTTPException(status_code=404, detail="game not found")
            if int(game.admin_user_id) != int(admin_user_id):
                raise HTTPException(status_code=403, detail="only game admin can call number")
            if str(game.status) != "RUNNING":
                raise HTTPException(status_code=400, detail="game is not RUNNING")

            max_number = int(GameService._get_setting(db, GameService.KEY_MAX_NUMBER, 99))
            if number < 1 or number > max_number:
                raise HTTPException(status_code=400, detail=f"number must be 1..{max_number}")

            # If already called -> return stable result (idempotent)
            exists = (
                db.execute(
                    select(GameCalledNumber).where(
                        GameCalledNumber.game_id == int(game_id),
                        GameCalledNumber.number == int(number),
                    )
                )
                .scalar_one_or_none()
            )
            if exists:
                called_count = db.execute(
                    select(func.count())
                    .select_from(GameCalledNumber)
                    .where(GameCalledNumber.game_id == int(game_id))
                ).scalar_one()

                payout_state = GameService._load_payout_state(game.payout_state_json)
                row = payout_state.get("row", {}) if isinstance(payout_state, dict) else {}
                result = {
                    "game_id": int(game_id),
                    "number": int(number),
                    "called_count": int(called_count),
                    "col_paid": int(game.col_paid),
                    "row_paid": int(_safe_int(payout_state.get("row_paid", 0), 0)),
                    "row_winner_user_ids": GameService._as_int_list(row.get("winner_user_ids")),
                    "row_winner_card_ids": GameService._as_int_list(row.get("winner_card_ids")),
                }
                try:
                    idem_set(idem_cache_key, result, ttl_sec=6 * 3600)
                except Exception:
                    pass
                return result

            # Insert called number
            row = GameCalledNumber(
                game_id=int(game_id),
                number=int(number),
                called_by=int(admin_user_id),
            )
            db.add(row)
            db.flush()

            # Event: NUMBER_CALLED (idempotent on game_id+number)
            try:
                GameEventService.emit(
                    db,
                    kind="NUMBER_CALLED",
                    game_id=int(game_id),
                    tg_group_id=int(game.tg_group_id),
                    actor_user_id=int(admin_user_id),
                    idem_key=f"NUMBER_CALLED:{game_id}:{number}",
                    payload={
                        "number": int(number),
                        "called_number_id": int(row.id),
                    },
                )

            except Exception:
                pass

            # Check payouts
            GameService._check_and_payout(db, game, called_number=int(number))

            called_count = db.execute(
                select(func.count())
                .select_from(GameCalledNumber)
                .where(GameCalledNumber.game_id == int(game_id))
            ).scalar_one()

            payout_state = GameService._load_payout_state(game.payout_state_json)
            row = payout_state.get("row", {}) if isinstance(payout_state, dict) else {}
            result = {
                "game_id": int(game_id),
                "number": int(number),
                "called_count": int(called_count),
                "col_paid": int(game.col_paid),
                "row_paid": int(_safe_int(payout_state.get("row_paid", 0), 0)),
                "row_winner_user_ids": GameService._as_int_list(row.get("winner_user_ids")),
                "row_winner_card_ids": GameService._as_int_list(row.get("winner_card_ids")),
            }

            try:
                idem_set(idem_cache_key, result, ttl_sec=6 * 3600)
            except Exception:
                pass

            return result

        finally:
            lock.release()

    @staticmethod
    def undo_last_call(
        db: Session,
        game_id: int,
        admin_user_id: int,
        idempotency_key: str,
    ) -> dict:
        idem_cache_key = f"idem:undo_call:{game_id}:{admin_user_id}:{idempotency_key}"
        try:
            cached = idem_get(idem_cache_key)
        except Exception:
            cached = None
        if cached:
            return cached

        # Share the same lock key with call_number to serialize call/undo operations.
        lock = RedisLock(f"game:{game_id}:call_lock", ttl_ms=8000)
        if not lock.acquire():
            raise HTTPException(status_code=409, detail="call/undo locked, try again")

        def _reverse_bucket_from_payload(
            *,
            bucket_kind: str,
            game_id_: int,
            call_number: int,
            payload: dict,
        ) -> None:
            winner_user_ids = GameService._as_int_list(payload.get("winner_user_ids"))
            winner_card_ids = GameService._as_int_list(payload.get("winner_card_ids"))
            amounts_by_card = GameService._as_int_list(payload.get("amounts_by_card"))

            if not amounts_by_card and winner_user_ids:
                total = int(_safe_int(payload.get("amount_total", 0), 0))
                amounts_by_card = GameService._split_equal(total, len(winner_user_ids))

            if len(winner_user_ids) != len(amounts_by_card):
                raise HTTPException(
                    status_code=500,
                    detail=f"invalid payout payload for undo ({bucket_kind})",
                )

            for idx, uid in enumerate(winner_user_ids):
                amount = int(amounts_by_card[idx])
                if amount <= 0:
                    continue
                card_id = winner_card_ids[idx] if idx < len(winner_card_ids) else (idx + 1)
                WalletService.debit(
                    db=db,
                    user_id=int(uid),
                    amount=int(amount),
                    reason="ADJUST",
                    idempotency_key=f"UNDO_{bucket_kind}:game:{game_id_}:num:{call_number}:card:{card_id}",
                    ref_type="GAME",
                    ref_id=int(game_id_),
                )

        try:
            game = (
                db.execute(select(Game).where(Game.id == game_id).with_for_update())
                .scalar_one_or_none()
            )
            if not game:
                raise HTTPException(status_code=404, detail="game not found")
            if int(game.admin_user_id) != int(admin_user_id):
                raise HTTPException(status_code=403, detail="only game admin can undo call")

            last_called = (
                db.execute(
                    select(GameCalledNumber)
                    .where(GameCalledNumber.game_id == int(game_id))
                    .order_by(GameCalledNumber.id.desc())
                    .limit(1)
                    .with_for_update()
                )
                .scalar_one_or_none()
            )
            if not last_called:
                raise HTTPException(status_code=400, detail="no called number to undo")

            undone_number = int(last_called.number)
            payout_state = GameService._load_payout_state(game.payout_state_json)
            row_info = payout_state.get("row", {}) if isinstance(payout_state.get("row"), dict) else {}
            col_info = payout_state.get("col", {}) if isinstance(payout_state.get("col"), dict) else {}
            row_paid = int(_safe_int(payout_state.get("row_paid", 0), 0))
            col_paid = int(game.col_paid)

            row_call_number = int(_safe_int(row_info.get("call_number", -1), -1))
            col_call_number = int(_safe_int(col_info.get("call_number", -1), -1))

            row_reversed = False

            # If last call caused ROW win, rollback row payouts and reopen game.
            if row_paid == 1 and row_call_number == undone_number and row_info:
                _reverse_bucket_from_payload(
                    bucket_kind="ROW",
                    game_id_=int(game_id),
                    call_number=undone_number,
                    payload=row_info,
                )
                row_reversed = True

                payout_state["row_paid"] = 0
                payout_state.pop("row", None)
                game.row_winner_user_id = None
                game.status = "RUNNING"

                # If row included column share, rollback col payout flags as well.
                includes_col_share = bool(row_info.get("includes_col_share", False))
                col_absorbed_same_call = bool(col_info.get("absorbed_into_row", False)) and col_call_number == undone_number
                if includes_col_share or col_absorbed_same_call:
                    game.col_paid = 0
                    payout_state.pop("col_paid", None)
                    payout_state.pop("col", None)

            # If last call caused COL win (and not ROW), rollback col payouts.
            if (not row_reversed) and col_paid == 1 and col_call_number == undone_number and col_info:
                _reverse_bucket_from_payload(
                    bucket_kind="COL",
                    game_id_=int(game_id),
                    call_number=undone_number,
                    payload=col_info,
                )
                game.col_paid = 0
                payout_state.pop("col_paid", None)
                payout_state.pop("col", None)

            db.delete(last_called)

            if not payout_state:
                game.payout_state_json = None
            else:
                game.payout_state_json = payout_state

            db.flush()

            called_count = db.execute(
                select(func.count())
                .select_from(GameCalledNumber)
                .where(GameCalledNumber.game_id == int(game_id))
            ).scalar_one()

            state_after = GameService._load_payout_state(game.payout_state_json)
            row_after = state_after.get("row", {}) if isinstance(state_after.get("row"), dict) else {}
            result = {
                "game_id": int(game_id),
                "undone_number": int(undone_number),
                "called_count": int(called_count),
                "status": str(game.status),
                "col_paid": int(game.col_paid),
                "row_paid": int(_safe_int(state_after.get("row_paid", 0), 0)),
                "row_winner_user_ids": GameService._as_int_list(row_after.get("winner_user_ids")),
                "row_winner_card_ids": GameService._as_int_list(row_after.get("winner_card_ids")),
            }

            try:
                GameEventService.emit(
                    db,
                    kind="NUMBER_UNDONE",
                    game_id=int(game_id),
                    tg_group_id=int(game.tg_group_id) if getattr(game, "tg_group_id", None) is not None else None,
                    actor_user_id=int(admin_user_id),
                    idem_key=f"NUMBER_UNDONE:{game_id}:{undone_number}:{idempotency_key}",
                    payload={
                        "number": int(undone_number),
                        "called_count": int(called_count),
                        "status": str(game.status),
                        "col_paid": int(game.col_paid),
                        "row_paid": int(_safe_int(state_after.get("row_paid", 0), 0)),
                    },
                )
            except Exception:
                pass

            try:
                idem_set(idem_cache_key, result, ttl_sec=6 * 3600)
            except Exception:
                pass

            return result
        finally:
            lock.release()

    @staticmethod
    def _check_and_payout(db: Session, game: Game, called_number: int) -> None:
        """
        Final rule:
        - Row checked first; row win ends game
        - Column can be paid only once and only if no row win in that call
        """
        game_id = int(game.id)
        tg_group_id = int(game.tg_group_id) if getattr(game, "tg_group_id", None) is not None else None

        def _emit_safe_v2(kind: str, idem_key: str, payload: dict | None = None) -> None:
            try:
                GameEventService.emit(
                    db,
                    kind=kind,
                    game_id=game_id,
                    tg_group_id=tg_group_id,
                    actor_user_id=None,
                    idem_key=idem_key,
                    payload=payload,
                )
            except Exception:
                pass

        # ---- New payout flow (ROW first, COL second; no FULL-card payout) ----
        called = db.execute(
            select(GameCalledNumber.number).where(GameCalledNumber.game_id == game_id)
        ).scalars().all()
        called_set = {int(x) for x in called}

        cards = db.execute(
            select(GameCard).where(GameCard.game_id == game_id)
        ).scalars().all()

        payout_state = GameService._load_payout_state(game.payout_state_json)
        col_paid = int(game.col_paid) == 1
        row_paid = int(_safe_int(payout_state.get("row_paid", 0), 0)) == 1

        # 1) Check ROW first
        if not row_paid:
            row_winner_cards = GameService._winner_cards(cards, called_set, mode="ROW")
            if row_winner_cards:
                row_bucket = int(game.row_prize_amount)  # 60%
                col_bucket = int(game.col_prize_amount)  # 30%
                row_total = row_bucket + (0 if col_paid else col_bucket)

                shares = GameService._split_equal(row_total, len(row_winner_cards))
                winner_card_ids = [cid for cid, _ in row_winner_cards]
                winner_user_ids = [uid for _, uid in row_winner_cards]

                for idx, (card_id, uid) in enumerate(row_winner_cards):
                    amount = int(shares[idx])
                    if amount <= 0:
                        continue
                    WalletService.credit(
                        db=db,
                        user_id=int(uid),
                        amount=amount,
                        reason="PRIZE_ROW",
                        idempotency_key=f"PRIZE_ROW:game:{game_id}:card:{card_id}",
                        ref_type="GAME",
                        ref_id=game_id,
                    )

                payout_state["row_paid"] = 1
                payout_state["row"] = {
                    "winner_card_ids": winner_card_ids,
                    "winner_user_ids": winner_user_ids,
                    "amount_total": int(row_total),
                    "amounts_by_card": shares,
                    "call_number": int(called_number),
                    "includes_col_share": bool(not col_paid),
                }

                if not col_paid:
                    game.col_paid = 1
                    payout_state["col_paid"] = 1
                    payout_state["col"] = {
                        "winner_card_ids": winner_card_ids,
                        "winner_user_ids": winner_user_ids,
                        "amount_total": int(col_bucket),
                        "call_number": int(called_number),
                        "absorbed_into_row": True,
                    }

                game.payout_state_json = payout_state
                game.row_winner_user_id = int(winner_user_ids[0]) if winner_user_ids else None
                game.status = "ENDED"
                db.flush()

                _emit_safe_v2(
                    "PRIZE_ROW",
                    f"PRIZE_ROW:{game_id}",
                    {
                        "winner_card_ids": winner_card_ids,
                        "winner_user_ids": winner_user_ids,
                        "amount_total": int(row_total),
                        "amounts_by_card": shares,
                        "call_number": int(called_number),
                        "includes_col_share": bool(not col_paid),
                    },
                )
                _emit_safe_v2(
                    "GAME_ENDED",
                    f"GAME_ENDED:{game_id}",
                    {
                        "status": "ENDED",
                        "end_reason": "ROW_WIN",
                        "winner_card_ids": winner_card_ids,
                        "winner_user_ids": winner_user_ids,
                        "col_paid": int(game.col_paid),
                    },
                )
                return

        # 2) If no ROW winner and COL is not paid yet, check COL
        if not col_paid:
            col_winner_cards = GameService._winner_cards(cards, called_set, mode="COL")
            if col_winner_cards:
                col_total = int(game.col_prize_amount)
                shares = GameService._split_equal(col_total, len(col_winner_cards))
                winner_card_ids = [cid for cid, _ in col_winner_cards]
                winner_user_ids = [uid for _, uid in col_winner_cards]

                for idx, (card_id, uid) in enumerate(col_winner_cards):
                    amount = int(shares[idx])
                    if amount <= 0:
                        continue
                    WalletService.credit(
                        db=db,
                        user_id=int(uid),
                        amount=amount,
                        reason="PRIZE_COL",
                        idempotency_key=f"PRIZE_COL:game:{game_id}:card:{card_id}",
                        ref_type="GAME",
                        ref_id=game_id,
                    )

                payout_state["col_paid"] = 1
                payout_state["col"] = {
                    "winner_card_ids": winner_card_ids,
                    "winner_user_ids": winner_user_ids,
                    "amount_total": int(col_total),
                    "amounts_by_card": shares,
                    "call_number": int(called_number),
                    "absorbed_into_row": False,
                }

                game.col_paid = 1
                game.payout_state_json = payout_state
                db.flush()

                _emit_safe_v2(
                    "PRIZE_COL",
                    f"PRIZE_COL:{game_id}",
                    {
                        "winner_card_ids": winner_card_ids,
                        "winner_user_ids": winner_user_ids,
                        "amount_total": int(col_total),
                        "amounts_by_card": shares,
                        "call_number": int(called_number),
                    },
                )
        return

    @staticmethod
    def get_user_cards(db: Session, game_id: int, user_id: int) -> list[dict]:
        rows = db.execute(
            select(GameCard)
            .where(GameCard.game_id == game_id, GameCard.user_id == user_id)
            .order_by(GameCard.id.asc())
        ).scalars().all()

        out: list[dict] = []
        for c in rows:
            nums = c.numbers_json
            if isinstance(nums, str):
                nums = json.loads(nums)
            out.append(
                {
                    "card_id": int(c.id),
                    "fingerprint": str(c.fingerprint),
                    "numbers": [int(x) for x in nums],
                }
            )
        return out

    @staticmethod
    def get_state(db: Session, game_id: int, last_n: int = 12) -> dict:
        g = db.execute(select(Game).where(Game.id == game_id)).scalar_one_or_none()
        if not g:
            raise HTTPException(status_code=404, detail="game not found")

        called = db.execute(
            select(GameCalledNumber.number)
            .where(GameCalledNumber.game_id == game_id)
            .order_by(GameCalledNumber.id.desc())
            .limit(last_n)
        ).scalars().all()

        called_list = [int(x) for x in called]
        last_number = called_list[0] if called_list else None

        payout_state = GameService._load_payout_state(g.payout_state_json)
        col_info = payout_state.get("col", {}) if isinstance(payout_state.get("col"), dict) else {}
        row_info = payout_state.get("row", {}) if isinstance(payout_state.get("row"), dict) else {}

        col_winner_card_ids = GameService._as_int_list(col_info.get("winner_card_ids"))
        col_winner_user_ids = GameService._as_int_list(col_info.get("winner_user_ids"))
        row_winner_card_ids = GameService._as_int_list(row_info.get("winner_card_ids"))
        row_winner_user_ids = GameService._as_int_list(row_info.get("winner_user_ids"))
        col_payout_total = int(_safe_int(col_info.get("amount_total", 0), 0))
        row_payout_total = int(_safe_int(row_info.get("amount_total", 0), 0))
        row_paid = int(_safe_int(payout_state.get("row_paid", 0), 0))

        return {
            "game_id": int(g.id),
            "tg_group_id": int(g.tg_group_id),
            "tg_topic_id": int(g.tg_topic_id) if getattr(g, "tg_topic_id", None) is not None else None,
            "status": str(g.status),
            "card_price": int(g.card_price),
            "sold_amount": int(g.sold_amount),
            "commission_amount": int(g.commission_amount),
            "prize_pool": int(g.prize_pool),
            "prize_locked": int(g.prize_locked),
            "col_prize_amount": int(g.col_prize_amount),
            "row_prize_amount": int(g.row_prize_amount),
            "called_numbers": list(reversed(called_list)),  # قدیمی→جدید
            "last_number": last_number,
            "col_paid": int(g.col_paid),
            "row_paid": int(row_paid),
            "col_winner_user_ids": col_winner_user_ids,
            "col_winner_card_ids": col_winner_card_ids,
            "row_winner_card_ids": row_winner_card_ids,
            "row_winner_user_ids": row_winner_user_ids,
            "col_payout_total": int(col_payout_total),
            "row_payout_total": int(row_payout_total),
        }

    @staticmethod
    def get_user_cards_preview(db: Session, game_id: int, user_id: int) -> dict:
        """
        خروجی آماده برای پیام خصوصی/پیش‌نمایش:
        - called_numbers: لیست اعداد خوانده‌شده
        - cards: هر کارت شامل grid_text + fingerprint
        """
        g = db.execute(select(Game).where(Game.id == game_id)).scalar_one_or_none()
        if not g:
            raise HTTPException(status_code=404, detail="game not found")

        called = db.execute(
            select(GameCalledNumber.number)
            .where(GameCalledNumber.game_id == game_id)
            .order_by(GameCalledNumber.id.asc())
        ).scalars().all()
        called_numbers = [int(x) for x in called]
        called_set = set(called_numbers)

        cards_rows = db.execute(
            select(GameCard)
            .where(GameCard.game_id == game_id, GameCard.user_id == user_id)
            .order_by(GameCard.id.asc())
        ).scalars().all()

        def _fmt_cell(n: int) -> str:
            return f"[{n:02d}]" if n in called_set else f" {n:02d} "

        def _grid_text(nums: list[int]) -> str:
            rows = []
            for r in range(4):
                row_nums = nums[r * 5 : (r + 1) * 5]
                rows.append(" ".join(_fmt_cell(int(x)) for x in row_nums))
            return "\n".join(rows)

        out_cards = []
        for c in cards_rows:
            nums = c.numbers_json
            if isinstance(nums, str):
                nums = json.loads(nums)
            nums = [int(x) for x in nums]

            if len(nums) != 20:
                raise HTTPException(status_code=500, detail=f"invalid card numbers count: card_id={c.id}")

            out_cards.append(
                {
                    "card_id": int(c.id),
                    "fingerprint": str(c.fingerprint),
                    "grid_text": _grid_text(nums),
                }
            )

        return {
            "game_id": int(game_id),
            "user_id": int(user_id),
            "called_numbers": called_numbers,
            "cards": out_cards,
        }



