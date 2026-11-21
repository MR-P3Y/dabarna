"""Authenticated, read-only tracking with SQL-level ownership and pagination."""
from datetime import date, datetime, time, timezone
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, or_, and_, func, literal, union_all, false
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.mini_security import get_mini_user_id
from app.models.user import User
from app.models.wallet import Wallet, WalletTx
from app.models.finance import DepositRequest, WithdrawRequest
from app.models.crypto import CryptoDepositRequest
from app.models.game import Game, GameCard, GamePurchase, GameCalledNumber
from app.models.admin_audit import AdminAuditLog
from app.models.game_event import GameEvent
from app.routers.mini_router import (
    _mini_role_names_for_user, _mini_config_roles_for_user, _numbers_from_json,
    _prize_label_for_rule,
)
from app.utils.messages import stored_rule, RULE_ERROR
from app.utils.numerals import normalize_digits

router = APIRouter(prefix="/mini-api/tracking", tags=["tracking"])
Kind = Literal["deposit", "withdraw", "crypto", "tx", "game", "card", "user"]
MODELS = dict(deposit=DepositRequest, withdraw=WithdrawRequest, crypto=CryptoDepositRequest,
              tx=WalletTx, game=Game, card=GameCard, user=User)
TITLES = dict(deposit="واریز بانکی", withdraw="برداشت", crypto="واریز رمزارز",
              tx="تراکنش کیف پول", game="بازی", card="کارت", user="کاربر")
STATUS = dict(LOBBY="در انتظار شروع", RUNNING="در حال اجرا", ENDED="پایان‌یافته",
              AWAITING_RECEIPT="در انتظار رسید", PENDING_REVIEW="در انتظار بررسی",
              PENDING="در انتظار بررسی", APPROVED="تأیید شده", REJECTED="رد شده",
              PAID="پرداخت ثبت شده", WAITING_PAYMENT="در انتظار پرداخت",
              CONFIRMING="در انتظار تأیید شبکه", CREDITED="اعتبار ثبت شده",
              EXPIRED="منقضی شده", NEEDS_REVIEW="نیازمند بررسی", CANCELLED="لغو شده",
              RECORDED="ثبت شده")
PREFIX = dict(deposit="DEP", withdraw="WDR", tx="WTX", card="CARD", user="UID", crypto="CRYPTO", game="GID")
AUDIT_TYPE = dict(deposit="deposit_request", withdraw="withdraw_request",
                  crypto="crypto_deposit_request", tx="wallet_tx", game="game", card="game_card", user="user")


def access(db, uid):
    user = db.get(User, uid)
    if user is None:
        raise HTTPException(401, "نشست معتبر نیست.")
    roles = set(_mini_role_names_for_user(db, uid)) | set(_mini_config_roles_for_user(uid, user.tg_user_id))
    return dict(uid=uid, roles=roles, finance=bool(roles & {"SUPER_ADMIN", "FINANCE_ADMIN"}),
                superuser="SUPER_ADMIN" in roles, operator=bool(roles & {"ADMIN", "GAME_OPERATOR"}))


def scope(kind, a):
    uid = a["uid"]
    managed = select(Game.id).where(Game.admin_user_id == uid) if a["operator"] else select(Game.id).where(false())
    games = or_(Game.id.in_(select(GameCard.game_id).where(GameCard.user_id == uid)),
                Game.id.in_(managed))
    if kind == "game":
        return literal(True) if a["superuser"] or a["finance"] else games
    if kind == "card":
        return literal(True) if a["superuser"] or a["finance"] else or_(GameCard.user_id == uid, GameCard.game_id.in_(managed))
    if kind == "user":
        return literal(True) if a["finance"] else or_(User.id == uid, User.id.in_(select(GameCard.user_id).where(GameCard.game_id.in_(managed))))
    if a["finance"]:
        return literal(True)
    if kind == "tx":
        return WalletTx.wallet_id.in_(select(Wallet.id).where(Wallet.user_id == uid))
    return MODELS[kind].user_id == uid


def allowed(db, kind, ident, a):
    row = db.scalar(select(MODELS[kind]).where(MODELS[kind].id == ident, scope(kind, a)))
    if row is None:
        raise HTTPException(404, "مورد قابل‌دسترسی پیدا نشد.")
    return row


def code(kind, row):
    if kind == "game" and row.display_code:
        return row.display_code
    if kind == "crypto":
        return row.public_id if row.public_id.upper().startswith("DAV-") else "DAV-" + row.public_id
    return f"DAV-{PREFIX[kind]}-{row.id:06d}"


def iso(value):
    if not value:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat() if isinstance(value, datetime) and value.tzinfo is None else str(value)


def summary(kind, row):
    status = getattr(row, "status", "RECORDED")
    return dict(kind=kind, id=row.id, code=code(kind, row), title=TITLES[kind],
                status=status, status_label=STATUS.get(status, status),
                amount=getattr(row, "amount_toman", getattr(row, "amount", None)),
                created_at=iso(row.created_at))


def match(kind, query):
    model = MODELS[kind]
    q = normalize_digits(query).strip()
    compact = re.sub(r"\s+", "", q)
    upper = compact.upper()
    tagged = re.fullmatch(r"(?:DAV-)?(DEP|WDR|WTX|GID|CARD|UID|CRYPTO)[:-]0*(\d+)", upper)
    if tagged:
        if len(tagged[2].lstrip("0")) > 18:
            return false()
        return model.id == int(tagged[2]) if PREFIX[kind] == tagged[1] else false()
    if not q:
        return literal(True)
    numeric = int(compact) if compact.isdecimal() and len(compact) <= 18 else None
    clauses = [model.id == numeric] if numeric is not None else []
    if kind == "game":
        clauses.append(func.upper(Game.display_code) == upper)
    if kind == "card":
        pair = re.fullmatch(r"(.+?)[/#](\d+)", upper)
        if pair and len(pair[2]) <= 18:
            game_clause = func.upper(Game.display_code) == pair[1]
            if pair[1].isdecimal() and len(pair[1]) <= 18:
                game_clause = Game.id == int(pair[1])
            clauses.append(and_(GameCard.game_id.in_(select(Game.id).where(game_clause)), GameCard.display_serial == int(pair[2])))
    if kind == "withdraw":
        clauses.append(WithdrawRequest.paid_tracking == q)
    if kind == "crypto":
        clauses.extend([func.upper(CryptoDepositRequest.public_id).in_([upper, upper.removeprefix("DAV-")]),
                        CryptoDepositRequest.tx_hash == q])
    if kind == "user":
        clauses.append(func.lower(User.username) == q.lstrip("@").lower())
        if numeric is not None:
            clauses.append(User.tg_user_id == numeric)
    return or_(*clauses) if clauses else false()


def search_rows(db, a, q, kind, offset, limit, status, since, until, owner=None, game=None):
    queries = []
    for key, model in MODELS.items():
        if kind and key != kind:
            continue
        conditions = [scope(key, a), match(key, q)]
        if status:
            conditions.append(getattr(model, "status", literal("RECORDED")) == status)
        if since:
            conditions.append(model.created_at >= datetime.combine(since, time.min))
        if until:
            conditions.append(model.created_at <= datetime.combine(until, time.max))
        if owner is not None:
            if key == "tx":
                conditions.append(WalletTx.wallet_id.in_(select(Wallet.id).where(Wallet.user_id == owner)))
            elif key == "game":
                conditions.append(Game.id.in_(select(GameCard.game_id).where(GameCard.user_id == owner)))
            else:
                conditions.append(getattr(model, "user_id", model.id) == owner)
        if game is not None:
            if key == "tx":
                conditions.extend([WalletTx.ref_type == "GAME", WalletTx.ref_id == game])
            elif key == "user":
                conditions.append(User.id.in_(select(GameCard.user_id).where(GameCard.game_id == game)))
            elif key == "card":
                conditions.append(GameCard.game_id == game)
            else:
                conditions.append(false())
        queries.append(select(literal(key).label("kind"), model.id.label("id"), model.created_at.label("created_at")).where(*conditions))
    combined = union_all(*queries).subquery()
    total = db.scalar(select(func.count()).select_from(combined))
    rows = db.execute(select(combined).order_by(combined.c.created_at.desc(), combined.c.kind, combined.c.id.desc()).offset(offset).limit(limit))
    items = [summary(r.kind, allowed(db, r.kind, r.id, a)) for r in rows]
    return dict(items=items, total=total, offset=offset, limit=limit, fetched_at=iso(datetime.now(timezone.utc)))


@router.get("/search")
def search(response: Response, q: str = Query("", max_length=180), kind: Kind | None = None,
           offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50),
           status: str = Query("", max_length=32), since: date | None = None, until: date | None = None,
           owner: int | None = None, game: int | None = None,
           user_id: int = Depends(get_mini_user_id), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "private, no-store"
    if since and until and since > until:
        raise HTTPException(422, "تاریخ پایان باید پس از شروع باشد.")
    a = access(db, user_id)
    if owner is not None:
        allowed(db, "user", owner, a)
    if game is not None:
        allowed(db, "game", game, a)
    return search_rows(db, a, q, kind, offset, limit, status, since, until, owner, game)


@router.get("/{kind}/{ident}")
def detail(kind: Kind, ident: int, response: Response, offset: int = Query(0, ge=0),
           user_id: int = Depends(get_mini_user_id), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "private, no-store"
    a = access(db, user_id)
    row = allowed(db, kind, ident, a)
    out = summary(kind, row)
    fields, links, timeline = [], [], []
    def field(label, value):
        if value is not None and value != "":
            fields.append(dict(label=label, value=str(value)))
    def link(key, pk):
        if pk:
            target = db.scalar(select(MODELS[key]).where(MODELS[key].id == pk, scope(key, a)))
            if target is not None:
                item = summary(key, target)
                if item not in links:
                    links.append(item)
    def event(label, at):
        if at:
            timeline.append(dict(label=label, at=iso(at)))
    event("ثبت", row.created_at)
    owner_id = getattr(row, "user_id", None)
    if kind == "tx":
        owner_id = db.scalar(select(Wallet.user_id).where(Wallet.id == row.wallet_id))
        field("جهت", "افزایش موجودی" if row.direction == "CREDIT" else "کاهش موجودی")
        label = {"BUY_CARDS":"خرید کارت","DEPOSIT_MANUAL":"واریز بانکی","DEPOSIT_GATEWAY":"واریز درگاه",
                 "DEPOSIT_CRYPTO":"واریز رمزارز","WITHDRAW":"برداشت","ADJUST":"اصلاح ثبت‌شده"}.get(row.reason, row.reason)
        if row.ref_type == "GAME":
            g = db.get(Game, row.ref_id)
            if g:
                if row.reason in ("PRIZE_COL", "PRIZE_ROW"):
                    label = _prize_label_for_rule(row.reason, stored_rule(g.game_rule, g.card_layout_version))
                link("game", g.id)
        field("علت ثبت", label)
        for key in ("deposit", "withdraw", "crypto"):
            target = db.scalar(select(MODELS[key]).where(MODELS[key].wallet_tx_id == row.id, scope(key, a)).limit(1))
            if target:
                link(key, target.id)
    if kind in ("deposit", "withdraw", "crypto"):
        link("tx", row.wallet_tx_id)
        field("دلیل بررسی", getattr(row, "rejection_reason", None) or getattr(row, "failure_reason", None))
        event("بررسی درخواست", getattr(row, "reviewed_at", None))
        if kind == "withdraw":
            field("کد پیگیری پرداخت", row.paid_tracking)
        if kind == "deposit":
            field("رسید پیوست", "دارد" if row.receipt_file_id or row.receipt_path else "هنوز ارسال نشده")
        if kind == "crypto":
            field("شبکه", row.network)
            field("ارز", row.asset)
            field("هش تراکنش", row.tx_hash)
            field("تأیید شبکه", f"{row.confirmation_count or 0} از {row.required_confirmations or 1}")
            for attr, label in [("detected_at", "مشاهده پرداخت"), ("confirmed_at", "تأیید شبکه"), ("credited_at", "ثبت اعتبار")]:
                event(label, getattr(row, attr))
        if row.wallet_tx_id:
            tx = db.get(WalletTx, row.wallet_tx_id)
            valid_wallet = tx and db.scalar(select(Wallet.user_id).where(Wallet.id == tx.wallet_id)) == row.user_id
            if valid_wallet:
                event("ثبت تراکنش کیف پول", tx.created_at)
                field("ثبت در کیف پول", "تراکنش مرتبط ثبت شده است")
            else:
                field("ثبت در کیف پول", "ارتباط تراکنش قابل تأیید نیست")
        else:
            field("ثبت در کیف پول", "هنوز تراکنش مرتبط ثبت نشده است")
        field("مرحله بعد", {"AWAITING_RECEIPT":"رسید پرداخت را از بخش کیف پول ارسال کنید.",
              "PENDING":"در انتظار بررسی مدیر", "PENDING_REVIEW":"در انتظار بررسی مدیر",
              "WAITING_PAYMENT":"در انتظار پرداخت", "CONFIRMING":"در انتظار تأییدهای شبکه",
              "NEEDS_REVIEW":"در انتظار بررسی مالی", "REJECTED":"دلیل رد را بررسی کنید و برای پیگیری با پشتیبانی تماس بگیرید."}.get(row.status))
    if kind in ("game", "card"):
        g = row if kind == "game" else allowed(db, "game", row.game_id, a)
        rule = stored_rule(g.game_rule, g.card_layout_version)
        field("قانون", {"LINE":"خطی، تورنا ۳ عدد و خطی ۵ عدد در یک ردیف", "FULL_CARD":"پرکردنی، تکمیل ۱۵ عدد", "LEGACY":"قدیمی، تورنا ستون ۴عددی و برد ردیف ۵عددی"}.get(rule, RULE_ERROR))
        field("سطح", g.game_level)
        field("قیمت کارت به تومان", g.card_price)
        field("صندوق جایزه به تومان", g.prize_pool)
        field("کمیسیون بازی", f"{float(g.commission_rate)*100:g}٪")
        field("شماره‌خوان", {"AUTO":"خودکار", "MANUAL":"دستی"}.get(g.draw_mode, "هنوز ثبت نشده"))
        event("شروع واقعی بازی", g.started_at)
        event("پایان واقعی بازی", g.ended_at)
        called = list(db.scalars(select(GameCalledNumber.number).where(GameCalledNumber.game_id == g.id).order_by(GameCalledNumber.id)))
        out["called"] = called
        if kind == "card":
            link("game", g.id)
            field("کد بازی و کارت", f"{g.display_code or g.id}/{row.display_serial}" if row.display_serial else None)
            field("شماره کارت در بازی", row.display_serial)
            purchase = db.get(GamePurchase, row.purchase_id)
            if purchase:
                link("tx", purchase.wallet_tx_id)
            try:
                nums = _numbers_from_json(row.numbers_json)
            except (TypeError, ValueError):
                nums = []
            expected = 20 if rule == "LEGACY" else 27
            nonempty = [n for n in nums if n]
            valid = (len(nums) == expected and len(nonempty) == (20 if rule == "LEGACY" else 15)
                     and len(set(nonempty)) == len(nonempty) and all(1 <= n <= 90 for n in nonempty)
                     and (rule == "LEGACY" or all(sum(bool(n) for n in nums[i:i+9]) == 5 for i in (0,9,18))))
            if rule == "UNKNOWN" or not valid:
                field("ساختار کارت", RULE_ERROR)
            else:
                out["card"] = dict(numbers=nums, columns=5 if rule == "LEGACY" else 9,
                                   matches=sum(n in called for n in nums if n))
        out["history"] = dict(game=g.id)
        # Expose only the requested card's registered prize events, never other winners' payloads.
        if kind == "card":
            wins = []
            for ev in db.scalars(select(GameEvent).where(GameEvent.game_id == g.id, GameEvent.kind.in_(["PRIZE_COL","PRIZE_ROW"])).order_by(GameEvent.id)):
                payload = ev.payload_json if isinstance(ev.payload_json, dict) else {}
                cards = payload.get("winner_card_ids") or []
                users = payload.get("winner_user_ids") or []
                amounts = payload.get("amounts_by_card") or []
                if not all(isinstance(v,list) for v in (cards,users,amounts)):
                    continue
                for i, cid in enumerate(cards):
                    if cid == row.id and i < len(users) and users[i] == row.user_id:
                        amount = amounts[i] if i < len(amounts) and type(amounts[i]) is int and amounts[i] >= 0 else None
                        wins.append(dict(label=_prize_label_for_rule(ev.kind, rule), amount=amount, at=iso(ev.created_at)))
            out["wins"] = wins
    if kind == "user":
        field("شناسه تلگرام", row.tg_user_id)
        field("نام کاربری", row.username)
        out["history"] = dict(owner=row.id)
    if owner_id:
        link("user", owner_id)
    audits = select(AdminAuditLog).where(AdminAuditLog.target_type == AUDIT_TYPE[kind], AdminAuditLog.target_id == ident)
    audit_total = 0
    audit_items = []
    if a["superuser"]:
        audit_total = db.scalar(select(func.count()).select_from(audits.subquery()))
        for item in db.scalars(audits.order_by(AdminAuditLog.id.desc()).offset(offset).limit(20)):
            # Only allow known descriptive fields. Credentials and raw payloads never leave the API.
            info = item.details_json if isinstance(item.details_json, dict) else {}
            audit_items.append(dict(action=item.action, actor=item.actor_user_id, at=iso(item.created_at),
                                   reason=str(info.get("reason") or info.get("rejection_reason") or "")[:500]))
    out.update(fields=fields, links=links, timeline=sorted(timeline, key=lambda v:v["at"]),
               audit=dict(items=audit_items, total=audit_total, offset=offset, limit=20),
               fetched_at=iso(datetime.now(timezone.utc)))
    return out
