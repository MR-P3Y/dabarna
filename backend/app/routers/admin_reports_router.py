from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.db import get_db
from app.core.admin_guard import require_admin_any, AdminIdentity

router = APIRouter(prefix="/admin/reports", tags=["admin-reports"])


def _parse_date_or_datetime(raw: str | None, *, end_of_day: bool = False) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            d = datetime.strptime(s, "%Y-%m-%d")
            if end_of_day:
                return d.replace(hour=23, minute=59, second=59, microsecond=999999)
            return d
        except Exception:
            raise HTTPException(status_code=400, detail=f"invalid date filter: {raw}")
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except Exception:
        raise HTTPException(status_code=400, detail=f"invalid date filter: {raw}")


def _as_json_dict(v: Any) -> dict[str, Any] | None:
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            loaded = json.loads(s)
        except Exception:
            return None
        return loaded if isinstance(loaded, dict) else None
    return None


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


def _round_int(x: Decimal) -> int:
    return int(x.to_integral_value(rounding=ROUND_HALF_UP))


@router.get("/overview")
def overview(
    ident: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    games = db.execute(text("""
        SELECT
          COUNT(*) AS games_total,
          COALESCE(SUM(sold_amount),0) AS sold_total,
          COALESCE(SUM(commission_amount),0) AS commission_total,
          COALESCE(SUM(prize_pool),0) AS prize_pool_total,
          SUM(CASE WHEN status='RUNNING' THEN 1 ELSE 0 END) AS games_running,
          SUM(CASE WHEN status='ENDED' THEN 1 ELSE 0 END) AS games_ended
        FROM games
    """)).mappings().one()

    finance = db.execute(text("""
        SELECT
          COALESCE(SUM(CASE WHEN direction='CREDIT' THEN amount ELSE 0 END),0) AS wallet_credit_total,
          COALESCE(SUM(CASE WHEN direction='DEBIT' THEN amount ELSE 0 END),0) AS wallet_debit_total
        FROM wallet_txs
    """)).mappings().one()

    pending_withdraw = db.execute(text("""
        SELECT COUNT(*) AS pending_withdraw_count, COALESCE(SUM(amount),0) AS pending_withdraw_amount
        FROM withdraw_requests
        WHERE status IN ('PENDING','APPROVED')
    """)).mappings().one()

    return {
        "games": dict(games),
        "wallet_txs": dict(finance),
        "withdraws_pending": dict(pending_withdraw),
    }


@router.get("/games")
def list_games(
    ident: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
    status: str | None = Query(default=None),
    tg_group_id: int | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    where = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}
    if status:
        where.append("status = :status")
        params["status"] = status
    if tg_group_id:
        where.append("tg_group_id = :tg_group_id")
        params["tg_group_id"] = tg_group_id

    total = db.execute(text(f"""
        SELECT COUNT(*) AS c
        FROM games
        WHERE {" AND ".join(where)}
    """), params).mappings().one()["c"]

    items = db.execute(text(f"""
        SELECT
          id, tg_group_id, status,
          card_price, sold_amount, commission_amount, prize_pool,
          prize_locked, col_prize_amount, row_prize_amount,
          col_paid, row_winner_user_id,
          created_at
        FROM games
        WHERE {" AND ".join(where)}
        ORDER BY id DESC
        LIMIT :limit OFFSET :offset
    """), params).mappings().all()

    return {"total": int(total), "limit": limit, "offset": offset, "items": [dict(x) for x in items]}


@router.get("/games/{game_id}")
def game_report(
    game_id: int,
    ident: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
    events_limit: int = Query(default=50, ge=1, le=500),
):
    game = db.execute(text("""
        SELECT
          id, tg_group_id, admin_user_id, status,
          card_price, sold_amount, commission_amount, prize_pool,
          prize_locked, col_prize_amount, row_prize_amount,
          col_paid, payout_state_json, row_winner_user_id,
          created_at
        FROM games
        WHERE id = :game_id
    """), {"game_id": game_id}).mappings().one_or_none()

    if not game:
        raise HTTPException(status_code=404, detail="game not found")

    purchase_stats = db.execute(text("""
        SELECT
          COUNT(*) AS purchases_count,
          COALESCE(SUM(qty),0) AS cards_sold,
          COALESCE(SUM(total_price),0) AS sales_total
        FROM game_purchases
        WHERE game_id = :game_id
    """), {"game_id": game_id}).mappings().one()

    called = db.execute(text("""
        SELECT number, called_by, created_at
        FROM game_called_numbers
        WHERE game_id = :game_id
        ORDER BY id ASC
    """), {"game_id": game_id}).mappings().all()

    events = db.execute(text("""
        SELECT id, kind, idem_key, actor_user_id, tg_group_id, payload_json, created_at
        FROM game_events
        WHERE game_id = :game_id
        ORDER BY id DESC
        LIMIT :lim
    """), {"game_id": game_id, "lim": events_limit}).mappings().all()

    return {
        "game": dict(game),
        "purchases": dict(purchase_stats),
        "called_numbers": [dict(x) for x in called],
        "events": [dict(x) for x in events],
    }


@router.get("/integrity")
def integrity(
    ident: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    # 1) negative balances
    neg = db.execute(text("""
        SELECT COUNT(*) AS c
        FROM wallets
        WHERE balance < 0
    """)).mappings().one()

    # 2) duplicated wallet tx idem keys
    dup_idem = db.execute(text("""
        SELECT COUNT(*) AS c
        FROM (
          SELECT idempotency_key
          FROM wallet_txs
          WHERE idempotency_key IS NOT NULL AND idempotency_key <> ''
          GROUP BY idempotency_key
          HAVING COUNT(*) > 1
        ) t
    """)).mappings().one()

    # 3) games sold consistency
    games_mismatch = db.execute(text("""
        SELECT COUNT(*) AS c
        FROM (
          SELECT g.id
          FROM games g
          LEFT JOIN (
            SELECT game_id, COALESCE(SUM(total_price),0) AS s
            FROM game_purchases
            GROUP BY game_id
          ) p ON p.game_id = g.id
          WHERE COALESCE(p.s,0) <> COALESCE(g.sold_amount,0)
        ) x
    """)).mappings().one()

    return {
        "negative_balances": dict(neg),
        "duplicate_wallet_idempotency": dict(dup_idem),
        "games_sold_mismatch": dict(games_mismatch),
    }


@router.get("/games-summary")
def games_sales_summary(
    ident: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
    from_at: str | None = Query(default=None),
    to_at: str | None = Query(default=None),
    tg_group_id: int | None = Query(default=None),
    tg_topic_id: int | None = Query(default=None),
):
    _ = ident
    if not str(from_at or "").strip() or not str(to_at or "").strip():
        raise HTTPException(status_code=400, detail="both from_at and to_at are required")

    start_at = _parse_date_or_datetime(from_at, end_of_day=False)
    end_at = _parse_date_or_datetime(to_at, end_of_day=True)
    if start_at is None or end_at is None:
        raise HTTPException(status_code=400, detail="invalid date filter")
    if start_at > end_at:
        raise HTTPException(status_code=400, detail="created_from cannot be greater than created_to")

    purchases_where: list[str] = ["gp.created_at >= :from_at", "gp.created_at <= :to_at"]
    events_where: list[str] = ["ge.created_at >= :from_at", "ge.created_at <= :to_at"]
    params: dict[str, Any] = {"from_at": start_at, "to_at": end_at}

    if tg_group_id is not None:
        params["tg_group_id"] = int(tg_group_id)
        purchases_where.append("g.tg_group_id = :tg_group_id")
        events_where.append("g.tg_group_id = :tg_group_id")
    if tg_topic_id is not None:
        params["tg_topic_id"] = int(tg_topic_id)
        purchases_where.append("g.tg_topic_id = :tg_topic_id")
        events_where.append("g.tg_topic_id = :tg_topic_id")

    games_where: list[str] = ["g.created_at >= :from_at", "g.created_at <= :to_at"]
    if tg_group_id is not None:
        games_where.append("g.tg_group_id = :tg_group_id")
    if tg_topic_id is not None:
        games_where.append("g.tg_topic_id = :tg_topic_id")

    game_rows = db.execute(
        text(
            f"""
            SELECT g.id
            FROM games g
            WHERE {" AND ".join(games_where)}
            """
        ),
        params,
    ).mappings().all()

    purchase_rows = db.execute(
        text(
            f"""
            SELECT
              gp.game_id,
              gp.qty,
              gp.total_price,
              g.commission_rate
            FROM game_purchases gp
            JOIN games g ON g.id = gp.game_id
            WHERE {" AND ".join(purchases_where)}
            """
        ),
        params,
    ).mappings().all()

    activity_event_rows = db.execute(
        text(
            f"""
            SELECT DISTINCT ge.game_id
            FROM game_events ge
            JOIN games g ON g.id = ge.game_id
            WHERE {" AND ".join(events_where)}
            """
        ),
        params,
    ).mappings().all()

    purchases_count = 0
    cards_sold = 0
    sales_total = 0
    commission_total = 0
    game_ids: set[int] = {
        int(row.get("id") or 0)
        for row in game_rows
        if int(row.get("id") or 0) > 0
    }
    for row in activity_event_rows:
        gid = int(row.get("game_id") or 0)
        if gid > 0:
            game_ids.add(gid)

    for row in purchase_rows:
        purchases_count += 1
        qty = int(row.get("qty") or 0)
        total_price = int(row.get("total_price") or 0)
        cards_sold += max(0, qty)
        sales_total += max(0, total_price)

        gid = int(row.get("game_id") or 0)
        if gid > 0:
            game_ids.add(gid)

        try:
            rate = Decimal(str(row.get("commission_rate") or "0.1000"))
        except Exception:
            rate = Decimal("0.1000")
        commission_total += _round_int(Decimal(total_price) * rate)

    event_rows = db.execute(
        text(
            f"""
            SELECT
              ge.game_id,
              ge.kind,
              ge.payload_json
            FROM game_events ge
            JOIN games g ON g.id = ge.game_id
            WHERE {" AND ".join(events_where)}
              AND ge.kind IN ('PRIZE_COL', 'PRIZE_ROW')
            """
        ),
        params,
    ).mappings().all()

    row_winner_user_ids: set[int] = set()
    row_winner_card_ids: set[int] = set()
    col_winner_user_ids: set[int] = set()
    col_winner_card_ids: set[int] = set()
    row_events_count = 0
    col_events_count = 0

    for row in event_rows:
        gid = int(row.get("game_id") or 0)
        if gid > 0:
            game_ids.add(gid)

        kind = str(row.get("kind") or "").strip().upper()
        payload = _as_json_dict(row.get("payload_json")) or {}
        winner_user_ids = set(_as_int_list(payload.get("winner_user_ids")))
        winner_card_ids = set(_as_int_list(payload.get("winner_card_ids")))

        if kind == "PRIZE_ROW":
            row_events_count += 1
            row_winner_user_ids.update(winner_user_ids)
            row_winner_card_ids.update(winner_card_ids)
        elif kind == "PRIZE_COL":
            col_events_count += 1
            col_winner_user_ids.update(winner_user_ids)
            col_winner_card_ids.update(winner_card_ids)

    return {
        "from_at": start_at.isoformat(sep=" ", timespec="seconds"),
        "to_at": end_at.isoformat(sep=" ", timespec="seconds"),
        "tg_group_id": int(tg_group_id) if tg_group_id is not None else None,
        "tg_topic_id": int(tg_topic_id) if tg_topic_id is not None else None,
        "games_count": int(len(game_ids)),
        "purchases_count": int(purchases_count),
        "cards_sold": int(cards_sold),
        "sales_total": int(sales_total),
        "commission_total": int(commission_total),
        "prize_pool_total": int(max(0, sales_total - commission_total)),
        "row_winner_users_count": int(len(row_winner_user_ids)),
        "row_winner_cards_count": int(len(row_winner_card_ids)),
        "row_win_events_count": int(row_events_count),
        "col_winner_users_count": int(len(col_winner_user_ids)),
        "col_winner_cards_count": int(len(col_winner_card_ids)),
        "col_win_events_count": int(col_events_count),
    }
