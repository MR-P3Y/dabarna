from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.admin_guard import require_admin_any, AdminIdentity

router = APIRouter(prefix="/admin/events", tags=["admin-events"])


def _parse_payload(v: Any):
    """
    payload_json ممکن است:
    - dict/list (اگر از DB به صورت JSON type آمده باشد)
    - str (JSON string)
    - None
    """
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            # داده خراب/غیر JSON: خام برگردان تا crash نکند
            return {"_raw": v}
    return {"_raw": v}


@router.get("")
def list_events(
    ident: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
    game_id: int | None = Query(default=None),
    kind: str | None = Query(default=None),
    actor_user_id: int | None = Query(default=None),
    q: str | None = Query(default=None, description="search in idem_key"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    sql = """
        SELECT
          id, game_id, tg_group_id, kind, actor_user_id, idem_key, payload_json, created_at
        FROM game_events
        WHERE 1=1
          AND (:game_id IS NULL OR game_id = :game_id)
          AND (:kind IS NULL OR kind = :kind)
          AND (:actor_user_id IS NULL OR actor_user_id = :actor_user_id)
          AND (:q IS NULL OR idem_key LIKE CONCAT('%', :q, '%'))
        ORDER BY id DESC
        LIMIT :limit OFFSET :offset
    """

    rows = db.execute(
        text(sql),
        {
            "game_id": game_id,
            "kind": kind,
            "actor_user_id": actor_user_id,
            "q": q,
            "limit": limit,
            "offset": offset,
        },
    ).mappings().all()

    count_sql = """
        SELECT COUNT(*) AS c
        FROM game_events
        WHERE 1=1
          AND (:game_id IS NULL OR game_id = :game_id)
          AND (:kind IS NULL OR kind = :kind)
          AND (:actor_user_id IS NULL OR actor_user_id = :actor_user_id)
          AND (:q IS NULL OR idem_key LIKE CONCAT('%', :q, '%'))
    """
    total = db.execute(
        text(count_sql),
        {
            "game_id": game_id,
            "kind": kind,
            "actor_user_id": actor_user_id,
            "q": q,
        },
    ).mappings().one()["c"]

    items: list[dict] = []
    for r in rows:
        d = dict(r)
        d["payload"] = _parse_payload(d.get("payload_json"))
        d.pop("payload_json", None)
        items.append(d)

    return {
        "total": int(total),
        "limit": int(limit),
        "offset": int(offset),
        "items": items,
    }
