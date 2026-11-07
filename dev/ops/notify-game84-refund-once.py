#!/usr/bin/env python3
"""Send ONE private Telegram refund notice for committed Game 84 refunds.

One-time marker: existing Mini App refund-notification marker namespace.
A durable claim is written BEFORE contacting Telegram. If Telegram times out
after actually delivering the message, repeat invocations remain blocked.
No wallet/game writes. Do NOT retry blindly if delivery is uncertain.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import select
from app.core import config as cfg
from app.core.db import SessionLocal
from app.models.game import Game, GamePurchase, GameCalledNumber
from app.models.game_event import GameEvent
from app.models.settings import AppSetting
from app.models.user import User
from app.models.wallet import Wallet, WalletTx

GID = 84
MARKER = "mini_lobby_refund_notice_sent:84"
AMOUNT = 36000


def ensure(cond: bool, message: str):
    if not cond:
        raise RuntimeError("BLOCKER: " + message)


def checked_recipient(db):
    game = db.get(Game, GID)
    ensure(game is not None and str(game.status) == "ENDED", "game 84 not closed")
    ensure(game.ended_at is not None, "game ended_at missing")
    purchases = db.execute(
        select(GamePurchase).where(GamePurchase.game_id == GID)
    ).scalars().all()
    ensure(len(purchases) == 2 and sum(int(x.qty) for x in purchases) == 6
           and sum(int(x.total_price) for x in purchases) == AMOUNT,
           "wrong purchase shape or amount")
    users = {int(x.user_id) for x in purchases}
    ensure(len(users) == 1, "more than one refund recipient")
    uid = next(iter(users))
    u = db.get(User, uid)
    ensure(u is not None and int(u.tg_user_id or 0) > 0, "buyer Telegram user id missing")
    w = db.execute(select(Wallet).where(Wallet.user_id == uid)).scalar_one_or_none()
    ensure(w is not None, "refund wallet missing")
    txs = db.execute(select(WalletTx).where(
        WalletTx.ref_type == "GAME", WalletTx.ref_id == GID
    )).scalars().all()
    ensure(len(txs) == 4, "unexpected Game 84 wallet ledger count")
    by_id = {int(t.id): t for t in txs}
    credits = [t for t in txs if str(t.direction) == "CREDIT" and str(t.reason) == "ADJUST"]
    ensure(len(credits) == 2 and sum(int(t.amount) for t in credits) == AMOUNT,
           "refunds not exactly 36,000 in two credits")
    for p in purchases:
        debit = by_id.get(int(p.wallet_tx_id))
        expected_key = f"LOBBY_REFUND:game:84:purchase:{int(p.id)}"
        ref = [t for t in credits if str(t.idempotency_key) == expected_key]
        ensure(debit is not None and str(debit.reason) == "BUY_CARDS"
               and str(debit.direction) == "DEBIT"
               and int(debit.wallet_id) == int(w.id)
               and int(debit.amount) == int(p.total_price),
               "purchase debit mismatch")
        ensure(len(ref) == 1 and int(ref[0].wallet_id) == int(w.id)
               and int(ref[0].amount) == int(p.total_price),
               "purchase refund mismatch")
    events = db.execute(select(GameEvent).where(
        GameEvent.game_id == GID, GameEvent.kind == "GAME_LOBBY_CLOSED"
    )).scalars().all()
    ensure(len(events) == 1 and isinstance(events[0].payload_json, dict)
           and int(events[0].payload_json.get("refund_total") or 0) == AMOUNT,
           "game cancellation audit missing or incorrect")
    ensure(int(db.execute(select(__import__("sqlalchemy").func.count()).select_from(
        GameCalledNumber).where(GameCalledNumber.game_id == GID)).scalar_one()) == 0,
        "unexpected game draw history")
    return uid, int(u.tg_user_id)


def send_private_message(tg_id: int, token: str) -> int:
    text = (
        "✅ <b>بازگشت وجه بازی ۸۴</b>\n\n"
        "بازی شماره ۸۴ لغو شد.\n"
        "مبلغ <b>۳۶٬۰۰۰ تومان</b> بابت ۶ کارت خریداری‌شده "
        "به کیف پول شما بازگردانده شد.\n\n"
        "برای مشاهده موجودی و تراکنش‌ها، بخش «💰 کیف پول» ربات را باز کنید."
    )
    payload = json.dumps({
        "chat_id": int(tg_id), "text": text, "parse_mode": "HTML",
        "disable_notification": False,
    }).encode("utf-8")
    # Token exists only in process memory, never logged to stdout.
    req = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=12) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not parsed.get("ok"):
        raise RuntimeError("Telegram API did not acknowledge delivery")
    msg = parsed.get("result") or {}
    return int(msg["message_id"])


def main():
    token = str(cfg.TELEGRAM_BOT_TOKEN or "").strip()
    ensure(token and ":" in token, "Telegram token missing from backend")
    ensure(not bool(cfg.GAME_AUTO_DRAW_ENABLED)
           and not bool(cfg.GAME_AUTOPILOT_RUNTIME_ENABLED),
           "game automation flags must remain OFF")
    with SessionLocal() as db:
        ensure(db.get(AppSetting, MARKER) is None,
               "refund notification marker already exists; do not resend")
        uid, tg_id = checked_recipient(db)
        db.add(AppSetting(k=MARKER, v_json={
            "sent": True,
            "status": "CLAIMED_UNCONFIRMED",
            "notified_ok": 0,
            "notify_failed": 0,
            "no_tg_count": 0,
            "refund_total": AMOUNT,
            "refund_users_count": 1,
            "claimed_at": datetime.now(timezone.utc).isoformat(),
        }))
        db.commit()
    print("CLAIMED: Refund verified; one private Telegram notice will be attempted.")
    outcome = "UNCERTAIN"
    message_id = None
    try:
        message_id = send_private_message(tg_id, token)
        outcome = "SENT"
    except HTTPError as e:
        # Rejected HTTP status is definitive API failure. Do not auto-resend.
        outcome = "FAILED_HTTP_" + str(e.code)
    except (URLError, TimeoutError, Exception):
        # Timeout may occur after delivery. Cannot safely retry automatically.
        outcome = "UNCERTAIN"

    with SessionLocal() as db:
        marker = db.execute(
            select(AppSetting).where(AppSetting.k == MARKER).with_for_update()
        ).scalar_one()
        data = dict(marker.v_json)
        ensure(data.get("status") == "CLAIMED_UNCONFIRMED",
               "notification marker changed unexpectedly")
        data.update({
            "sent": True,  # prevents Mini App from duplicate notification
            "status": outcome,
            "notified_ok": int(outcome == "SENT"),
            "notify_failed": int(outcome != "SENT"),
            "telegram_message_id": message_id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        marker.v_json = data
        db.commit()
    print("NOTICE STATUS:", outcome)
    if outcome == "SENT":
        print("Telegram private message ID:", message_id)
        print("SUCCESS: User #", uid, "notified; no wallet/game mutation")
        return 0
    print("NOTICE NOT CONFIRMED: marker prevents automatic duplicate; check Telegram manually")
    return 3


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(type(e).__name__ + ": " + str(e))
        sys.exit(2)
