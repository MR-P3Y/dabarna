#!/usr/bin/env python3
"""One-off, fail-closed Game #84 cancellation and wallet-refund operation.

Runs INSIDE the already-deployed davarna-backend container.
Never modifies application source, flags, or tables' schema.
Approval scope: Game #84, exactly two purchases / six cards / 36,000 Toman.
Usage: python - --phase preflight|execute|verify [--expect FINGERPRINT]

preflight: read-only SQL transaction; returns a purchase fingerprint.
execute: game row lock, full revalidation, single transaction via
         GameService.close_lobby_game; checks ledger before COMMIT.
verify: read-only confirmation of closed game and exact refunds.
Telegram notifications are intentionally NOT sent here; messages must
never precede the financial COMMIT.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import config as cfg
from app.core.db import SessionLocal, engine
from app.models.game import Game, GameAutoDraw, GameCalledNumber, GameCard, GamePurchase
from app.models.game_autopilot import GameAutopilotConfig
from app.models.game_event import GameEvent
from app.models.wallet import Wallet, WalletTx
from app.services.game_service import GameService

GAME_ID = 84
PURCHASES = 2
CARDS = 6
EXPECTED_SALES = 36000
EXPECTED_COMMISSION = 3600
EXPECTED_POOL = 32400
EXPECTED_UNIT_PRICE = 6000
CANCEL_KEY = "ops:game84:cancel:authorized:20261107"
CANCEL_REASON = "لغو بازی آزمایشی ۸۴ و بازپرداخت کامل با تأیید مالک سیستم"


def ensure(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError("BLOCKER: " + message)


def check_runtime(db: Session) -> None:
    ensure(bool(cfg.GAME_AUTO_DRAW_ENABLED) is False,
           "AUTO DRAW runtime is enabled")
    ensure(bool(cfg.GAME_AUTOPILOT_RUNTIME_ENABLED) is False,
           "AUTOPILOT runtime is enabled")
    rev = db.connection().exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
    ensure(str(rev) == "20261104_0011",
           f"Unexpected schema revision: {rev}")
    low = db.get(GameAutopilotConfig, "LOW")
    ensure(low is not None, "LOW configuration not found")
    ensure(int(low.enabled or 0) == 0, "LOW scheduler enabled")
    ensure(str(low.scheduler_mode) == "MANUAL", "LOW scheduler not MANUAL")
    ensure(str(low.start_mode) == "MANUAL", "LOW start not MANUAL")
    ensure(str(low.draw_mode) == "MANUAL", "LOW draw not MANUAL")


def preconditions(db: Session, *, lock: bool) -> dict:
    # App buy/start/close code locks the game row first. A FOR UPDATE lock
    # therefore serializes this operation with all concurrent card buys.
    game_stmt = select(Game).where(Game.id == GAME_ID)
    game = db.execute(
        game_stmt.with_for_update() if lock else game_stmt
    ).scalar_one_or_none()
    ensure(game is not None, "game 84 missing")
    ensure(str(game.status) == "LOBBY", f"game status is {game.status}, not LOBBY")
    ensure(str(game.game_level) == "LOW", "game level changed")
    ensure(str(game.execution_source) == "ADMIN", "game execution source changed")
    ensure(str(game.draw_mode) == "MANUAL", "game draw mode changed")
    ensure(int(game.card_price) == EXPECTED_UNIT_PRICE, "card price changed")
    ensure(game.started_at is None and game.ended_at is None,
           "game already started or ended")
    ensure(game.draw_mode_locked_at is None, "game draw mode locked")
    ensure(game.row_winner_user_id is None and int(game.col_paid or 0) == 0,
           "winner/payout state exists")
    ensure(int(game.prize_locked or 0) == 0 and not game.payout_state_json,
           "prize already locked or payout state populated")
    ensure(
        (int(game.sold_amount), int(game.commission_amount), int(game.prize_pool))
        == (EXPECTED_SALES, EXPECTED_COMMISSION, EXPECTED_POOL),
        "recorded game sales/commission/pool changed",
    )

    called = db.execute(
        select(func.count()).select_from(GameCalledNumber)
        .where(GameCalledNumber.game_id == GAME_ID)
    ).scalar_one()
    ensure(int(called) == 0, "some numbers have already been called")

    auto = db.get(GameAutoDraw, GAME_ID)
    ensure(auto is None, "unexpected AUTO draw control exists")

    stmt = (
        select(GamePurchase)
        .where(GamePurchase.game_id == GAME_ID)
        .order_by(GamePurchase.id.asc())
    )
    purchases = db.execute(stmt.with_for_update() if lock else stmt).scalars().all()
    ensure(len(purchases) == PURCHASES, "purchase count is not exactly 2")
    buyer_ids = {int(p.user_id) for p in purchases}
    ensure(len(buyer_ids) == 1, "purchases belong to more than one buyer")
    user_id = next(iter(buyer_ids))
    ensure(
        sum(int(p.qty) for p in purchases) == CARDS
        and sum(int(p.total_price) for p in purchases) == EXPECTED_SALES,
        "purchase card count or total differs from approved values",
    )
    ensure(all(int(p.qty) > 0
               and int(p.unit_price) == EXPECTED_UNIT_PRICE
               and int(p.total_price) == int(p.qty) * EXPECTED_UNIT_PRICE
               for p in purchases),
           "purchase quantity/unit-price inconsistency")
    ensure(len({int(p.wallet_tx_id) for p in purchases}) == PURCHASES,
           "purchases share wallet debit transaction")

    # Lock the receiving wallet to freeze balance during this financial action.
    w_stmt = select(Wallet).where(Wallet.user_id == user_id)
    wallet = db.execute(w_stmt.with_for_update() if lock else w_stmt).scalar_one_or_none()
    ensure(wallet is not None, "buyer's wallet missing")
    before_balance = int(wallet.balance)
    ensure(before_balance >= 0, "wallet currently has negative balance")

    # Only two legitimate original purchase debits may reference this game.
    txs = db.execute(
        select(WalletTx).where(
            WalletTx.ref_type == "GAME", WalletTx.ref_id == GAME_ID
        ).order_by(WalletTx.id)
    ).scalars().all()
    ensure(len(txs) == PURCHASES, "unexpected existing GAME ledger transactions")
    tx_by_id = {int(t.id): t for t in txs}
    for p in purchases:
        tx = tx_by_id.get(int(p.wallet_tx_id))
        ensure(tx is not None, f"purchase {p.id} missing linked wallet debit")
        ensure(
            int(tx.wallet_id) == int(wallet.id)
            and str(tx.direction) == "DEBIT"
            and str(tx.reason) == "BUY_CARDS"
            and int(tx.amount) == int(p.total_price)
            and str(tx.ref_type) == "GAME"
            and int(tx.ref_id) == GAME_ID,
            f"purchase {p.id} does not match linked wallet debit",
        )

    # Detect even a refund with malformed ref_type/ref_id from a prior attempt.
    old_keys = db.execute(
        select(WalletTx.id).where(
            WalletTx.idempotency_key.like("LOBBY_REFUND:game:84:purchase:%")
        )
    ).scalars().all()
    ensure(not old_keys, "a previous Game 84 refund key already exists")
    old_close = db.execute(
        select(GameEvent.id).where(
            GameEvent.game_id == GAME_ID,
            GameEvent.kind == "GAME_LOBBY_CLOSED",
        )
    ).scalars().all()
    ensure(not old_close, "Game 84 has an existing close event")

    cards = db.execute(
        select(GameCard)
        .where(GameCard.game_id == GAME_ID)
        .order_by(GameCard.id.asc())
    ).scalars().all()
    ensure(len(cards) == CARDS, "actual game cards are not exactly 6")
    by_purchase = Counter(int(c.purchase_id) for c in cards)
    for p in purchases:
        ensure(
            by_purchase[int(p.id)] == int(p.qty)
            and all(
                int(c.user_id) == int(p.user_id)
                for c in cards if int(c.purchase_id) == int(p.id)
            ),
            f"cards are not correctly linked to purchase {p.id}",
        )

    check_runtime(db)
    digest_source = {
        "game_id": GAME_ID,
        "buyer_user_id": user_id,
        "game": [str(game.status), str(game.draw_mode), str(game.execution_source),
                 int(game.sold_amount), int(game.commission_amount), int(game.prize_pool)],
        "purchases": [
            [int(p.id), int(p.user_id), int(p.qty), int(p.unit_price),
             int(p.total_price), int(p.wallet_tx_id)]
            for p in purchases
        ],
        "wallet_id": int(wallet.id),
        "debits": [
            [int(t.id), int(t.wallet_id), int(t.amount), str(t.idempotency_key)]
            for t in txs
        ],
        "cards": sorted(int(c.id) for c in cards),
    }
    fingerprint = hashlib.sha256(
        json.dumps(digest_source, ensure_ascii=True, sort_keys=True).encode()
    ).hexdigest()
    return {
        "game": game,
        "purchases": purchases,
        "wallet": wallet,
        "balance_before": before_balance,
        "buyer_user_id": user_id,
        "fingerprint": fingerprint,
    }


def check_refunded(db: Session, *, wallet_id: int, purchases: list, before_balance: int | None = None) -> list:
    game = db.get(Game, GAME_ID)
    ensure(game is not None and str(game.status) == "ENDED",
           "game was not marked ENDED")
    ensure(game.ended_at is not None and game.started_at is None,
           "ended timestamp or started timestamp unexpected")
    ensure(all(int(getattr(game, field) or 0) == 0 for field in
               ("sold_amount", "commission_amount", "prize_pool",
                "col_prize_amount", "row_prize_amount", "prize_locked", "col_paid")),
           "game financial fields were not zeroed")
    ensure(not game.payout_state_json and game.row_winner_user_id is None,
           "game retained winner or payout state")

    txs = db.execute(
        select(WalletTx).where(
            WalletTx.ref_type == "GAME", WalletTx.ref_id == GAME_ID
        )
    ).scalars().all()
    debits = [t for t in txs if str(t.direction) == "DEBIT" and str(t.reason) == "BUY_CARDS"]
    credits = [t for t in txs if str(t.direction) == "CREDIT" and str(t.reason) == "ADJUST"]
    ensure(len(debits) == PURCHASES and len(credits) == PURCHASES and len(txs) == 2 * PURCHASES,
           "unexpected ledger entries after cancellation")
    keys = {str(t.idempotency_key): t for t in credits}
    ensure(len(keys) == PURCHASES and sum(int(t.amount) for t in credits) == EXPECTED_SALES,
           "incorrect number or total of refund credits")
    for p in purchases:
        key = f"LOBBY_REFUND:game:{GAME_ID}:purchase:{int(p.id)}"
        tx = keys.get(key)
        ensure(tx is not None and int(tx.wallet_id) == wallet_id
               and int(tx.amount) == int(p.total_price),
               f"refund for purchase {p.id} is missing or inconsistent")

    if before_balance is not None:
        balance = db.execute(
            select(Wallet.balance).where(Wallet.id == int(wallet_id)).with_for_update()
        ).scalar_one()
        ensure(int(balance) == before_balance + EXPECTED_SALES,
               "wallet balance did not increase by exactly 36,000")

    events = db.execute(
        select(GameEvent).where(
            GameEvent.game_id == GAME_ID,
            GameEvent.kind == "GAME_LOBBY_CLOSED",
        )
    ).scalars().all()
    ensure(len(events) == 1, "expected exactly one GAME_LOBBY_CLOSED event")
    payload = events[0].payload_json
    ensure(isinstance(payload, dict), "missing event refund payload")
    ensure(int(payload.get("refund_total") or -1) == EXPECTED_SALES,
           "refund amount in audit event does not match")
    ensure(int(payload.get("refund_users_count") or -1) == 1,
           "refund recipient count in audit event does not match")
    ensure(int(payload.get("refund_purchases_count") or -1) == PURCHASES,
           "refund purchase count in audit event does not match")
    return credits


def read_only_session():
    conn = engine.connect()
    try:
        conn.exec_driver_sql("START TRANSACTION READ ONLY")
        db = Session(bind=conn, expire_on_commit=False)
        try:
            yield db
        finally:
            db.close()
            conn.rollback()
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("preflight", "execute", "verify"), required=True)
    parser.add_argument("--expect", default="")
    args = parser.parse_args()

    if args.phase == "preflight":
        # Read-only operation; every condition is rechecked with locks during execution.
        yield_fn = read_only_session()
        db = next(yield_fn)
        try:
            snap = preconditions(db, lock=False)
            print("PREFLIGHT OK: Game 84 / 1 buyer / 2 purchases / 6 cards / 36,000")
            print("CURRENT_WALLET_BALANCE=", snap["balance_before"])
            print("FINGERPRINT=" + snap["fingerprint"])
        finally:
            try:
                next(yield_fn)
            except StopIteration:
                pass
        return 0

    if args.phase == "execute":
        ensure(len(args.expect) == 64 and all(c in "0123456789abcdef" for c in args.expect),
               "--expect fingerprint from most recent preflight is mandatory")
        with SessionLocal() as db:
            try:
                snap = preconditions(db, lock=True)
                ensure(snap["fingerprint"] == args.expect,
                       "snapshot fingerprint changed between preflight and execution")
                print("LOCKED PREFLIGHT OK: buyer and purchases unchanged")
                # In the live service, this uses a stable per-purchase idempotency key
                # and locks the game/purchases/wallet in the same transaction.
                GameService.close_lobby_game(
                    db=db,
                    game_id=GAME_ID,
                    admin_user_id=int(snap["game"].admin_user_id),
                    idempotency_key=CANCEL_KEY,
                    cancel_reason=CANCEL_REASON,
                    can_manage_any=False,
                )
                db.flush()
                credits = check_refunded(
                    db,
                    wallet_id=int(snap["wallet"].id),
                    purchases=snap["purchases"],
                    before_balance=snap["balance_before"],
                )
                ensure(len(credits) == 2, "wrong refund count")
                db.commit()
            except Exception:
                db.rollback()
                raise
        print("COMMITTED: Game 84 closed; two refunds total 36,000")
        print("Buyer internal ID:", snap["buyer_user_id"])
        print("Wallet balance before:", snap["balance_before"])
        print("Wallet balance after:", snap["balance_before"] + EXPECTED_SALES)
        print("Refund ledger IDs:", [int(t.id) for t in credits])
        print("NOTIFICATION: not sent (must follow committed refund)")
        return 0

    # Standalone verification also works after a connection interruption.
    with SessionLocal() as db:
        game = db.get(Game, GAME_ID)
        ensure(game is not None and str(game.status) == "ENDED",
               "Game 84 has not been closed")
        purchases = db.execute(
            select(GamePurchase).where(GamePurchase.game_id == GAME_ID)
            .order_by(GamePurchase.id)
        ).scalars().all()
        ensure(len(purchases) == PURCHASES and
               sum(int(p.total_price) for p in purchases) == EXPECTED_SALES and
               sum(int(p.qty) for p in purchases) == CARDS,
               "original purchases changed")
        user_ids = {int(p.user_id) for p in purchases}
        ensure(len(user_ids) == 1, "unexpected buyers")
        wallet = db.execute(
            select(Wallet).where(Wallet.user_id == next(iter(user_ids)))
        ).scalar_one()
        credits = check_refunded(db, wallet_id=int(wallet.id), purchases=purchases)
        print("VERIFIED: Game 84 ENDED, 2 exact refund credits, 36,000 total")
        print("Ledger refund IDs:", [int(t.id) for t in credits])
        db.rollback()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("STOPPED; no new commit if execution failed before COMMIT:")
        print(type(exc).__name__ + ": " + str(exc))
        sys.exit(2)
