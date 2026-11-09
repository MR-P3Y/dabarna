"""One-time compensated close of stalled, zero-draw AUTO games #86/#87.

Run inside the existing production backend with a host exclusive lock.
No prize payouts. Refund each verified purchase exactly once.
Rollback both games and every credit atomically on any failed invariant.
"""
import json
import os
from datetime import datetime, timezone

from sqlalchemy import func, select
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game import Game, GameAutoDraw, GameCalledNumber, GamePurchase, GameCard
from app.models.wallet import Wallet, WalletTx
from app.services.game_event_service import GameEventService
from app.services.wallet_service import WalletService

IDS = (86, 87)
EXPECTED_APPROVAL = "CLOSE_86_87_REFUND_PURCHASES_NO_PRIZES"
approval = os.getenv("DAVARNA_STALLED_AUTO_CLOSE_APPROVAL", "")
if approval != EXPECTED_APPROVAL:
    raise SystemExit("BLOCKER: explicit two-game compensated-close approval is required")
if cfg.GAME_AUTO_DRAW_ENABLED or cfg.GAME_AUTOPILOT_RUNTIME_ENABLED:
    raise SystemExit("BLOCKER: workers must be disabled while closing stalled games")

now = datetime.now(timezone.utc).replace(tzinfo=None)
out = []
with SessionLocal() as db:
    try:
        games = [db.execute(select(Game).where(Game.id == gid).with_for_update()).scalar_one_or_none() for gid in IDS]
        for gid, game in zip(IDS, games):
            if game is None or str(game.status) != "RUNNING" or str(game.draw_mode) != "AUTO":
                raise RuntimeError(f"BLOCKER: game {gid} not RUNNING/AUTO")
            control = db.execute(select(GameAutoDraw).where(
                GameAutoDraw.game_id == gid
            ).with_for_update()).scalar_one_or_none()
            if (control is None or str(control.status) != "RUNNING"
                    or int(control.cursor or 0) != 0 or int(game.col_paid or 0) != 0
                    or game.row_winner_user_id is not None or game.payout_state_json is not None):
                raise RuntimeError(f"BLOCKER: game {gid} control, cursor, or payout state differs")
            called = int(db.execute(select(func.count()).select_from(GameCalledNumber).where(
                GameCalledNumber.game_id == gid,
            )).scalar_one())
            if called != 0:
                raise RuntimeError(f"BLOCKER: game {gid} already has called numbers")
            purchases = db.execute(select(GamePurchase).where(
                GamePurchase.game_id == gid
            ).order_by(GamePurchase.id).with_for_update()).scalars().all()
            cards = db.execute(select(GameCard).where(GameCard.game_id == gid)).scalars().all()
            if len(cards) != sum(int(p.qty) for p in purchases):
                raise RuntimeError(f"BLOCKER: game {gid} card qty mismatch")
            card_counts = {}
            for card in cards:
                card_counts[(int(card.purchase_id), int(card.user_id))] = (
                    card_counts.get((int(card.purchase_id), int(card.user_id)), 0) + 1
                )
            purchase_sum = 0
            for p in purchases:
                if int(p.qty) <= 0 or int(p.total_price) != int(p.unit_price)*int(p.qty):
                    raise RuntimeError(f"BLOCKER: invalid purchase {p.id}")
                if card_counts.get((int(p.id), int(p.user_id))) != int(p.qty):
                    raise RuntimeError(f"BLOCKER: purchase cards inconsistent: {p.id}")
                original = db.get(WalletTx, int(p.wallet_tx_id))
                wallet = db.execute(select(Wallet).where(
                    Wallet.user_id == int(p.user_id)
                )).scalar_one_or_none()
                if (original is None or wallet is None
                        or int(original.wallet_id) != int(wallet.id)
                        or str(original.direction) != "DEBIT"
                        or str(original.reason) != "BUY_CARDS"
                        or str(original.ref_type) != "GAME"
                        or int(original.ref_id or 0) != gid
                        or int(original.amount) != int(p.total_price)):
                    raise RuntimeError(f"BLOCKER: purchase debit does not reconcile: {p.id}")
                purchase_sum += int(p.total_price)
            if int(game.sold_amount or 0) != purchase_sum:
                raise RuntimeError(f"BLOCKER: game {gid} sales != purchases")
            if int(game.prize_pool or 0)+int(game.commission_amount or 0) != purchase_sum:
                raise RuntimeError(f"BLOCKER: game {gid} pool/commission mismatch")
            old_credits = db.execute(select(WalletTx).where(
                WalletTx.ref_type == "GAME", WalletTx.ref_id == gid,
                WalletTx.direction == "CREDIT",
            )).scalars().all()
            if old_credits:
                raise RuntimeError(f"BLOCKER: game {gid} already has credits, prizes or refunds")

            # Once EVERY preflight passed, only compensating purchase refunds.
            out.append((gid, game, control, purchases, purchase_sum))
        # Confirm no other active auto games would start unexpectedly when worker enabled.
        other_running = db.execute(select(Game.id).where(
            Game.id.not_in(IDS), Game.status == "RUNNING", Game.draw_mode == "AUTO",
        )).scalars().all()
        if other_running:
            raise RuntimeError(f"BLOCKER: other running AUTO games exist: {other_running}")
        results=[]
        for gid, game, control, purchases, purchase_sum in out:
            for p in purchases:
                WalletService.credit(
                    db=db, user_id=int(p.user_id), amount=int(p.total_price),
                    reason="ADJUST",
                    idempotency_key=f"STALLED_AUTO_REFUND:game:{gid}:purchase:{int(p.id)}",
                    ref_type="GAME", ref_id=gid,
                )
            control.status = "STOPPED"
            control.next_draw_at = None
            control.stopped_at = now
            game.status = "ENDED"
            game.ended_at = now
            game.sold_amount = 0
            game.commission_amount = 0
            game.prize_pool = 0
            game.col_prize_amount = 0
            game.row_prize_amount = 0
            game.col_paid = 0
            game.prize_locked = 0
            game.row_winner_user_id = None
            game.payout_state_json = None
            db.flush()
            GameEventService.emit(
                db, kind="GAME_ENDED", game_id=gid,
                tg_group_id=int(game.tg_group_id),
                actor_user_id=int(game.admin_user_id),
                idem_key=f"GAME_ENDED:stalled_auto_refunded:{gid}",
                payload={
                    "reason": "stalled_auto_worker_disabled",
                    "zero_called_numbers": True,
                    "no_prizes_awarded": True,
                    "purchase_refunds_toman": purchase_sum,
                    "refund_purchase_count": len(purchases),
                },
            )
            results.append({"id":gid,"status":"ENDED","auto":"STOPPED",
                            "refunded_toman":purchase_sum,"purchases":len(purchases)})
        db.commit()
        print("CLOSED_STALLED_AUTO_GAMES", json.dumps(results, ensure_ascii=False))
    except Exception:
        db.rollback()
        raise
