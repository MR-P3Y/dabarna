from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_STORE_PATH = Path("storage/notif_state.json")


def _load() -> dict[str, Any]:
    if not _STORE_PATH.exists():
        return {"subs": {}, "last": {}, "events": {}, "meta": {}}
    try:
        data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"subs": {}, "last": {}, "events": {}, "meta": {}}
        data.setdefault("subs", {})
        data.setdefault("last", {})
        data.setdefault("events", {})
        data.setdefault("meta", {})
        return data
    except Exception:
        return {"subs": {}, "last": {}, "events": {}, "meta": {}}


def _save(data: dict[str, Any]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def subscribe(tg_user_id: int, game_id: int) -> None:
    data = _load()
    subs = data.setdefault("subs", {})
    g = str(int(game_id))
    users = set(subs.get(g, []))
    users.add(int(tg_user_id))
    subs[g] = sorted(users)
    _save(data)


def unsubscribe(tg_user_id: int, game_id: int) -> None:
    data = _load()
    subs = data.setdefault("subs", {})
    g = str(int(game_id))
    users = set(subs.get(g, []))
    users.discard(int(tg_user_id))
    subs[g] = sorted(users)
    _save(data)


def get_subscribers(game_id: int) -> list[int]:
    data = _load()
    return [int(x) for x in (data.get("subs", {}).get(str(int(game_id)), []) or [])]


def is_subscribed(tg_user_id: int, game_id: int) -> bool:
    data = _load()
    users = data.get("subs", {}).get(str(int(game_id)), []) or []
    uid = int(tg_user_id)
    return uid in {int(x) for x in users}


def get_user_subscription_map(game_ids: list[int], tg_user_id: int) -> dict[int, bool]:
    data = _load()
    subs = data.get("subs", {}) or {}
    uid = int(tg_user_id)
    out: dict[int, bool] = {}
    for gid in game_ids:
        users = subs.get(str(int(gid)), []) or []
        out[int(gid)] = uid in {int(x) for x in users}
    return out


def set_last_seen_count(game_id: int, count: int) -> None:
    data = _load()
    last = data.setdefault("last", {})
    last[str(int(game_id))] = int(count)
    _save(data)


def get_last_seen_count(game_id: int) -> int:
    data = _load()
    return int((data.get("last", {}).get(str(int(game_id)), 0)) or 0)


def list_tracked_game_ids() -> list[int]:
    data = _load()
    subs = data.get("subs", {}) or {}
    return [int(k) for k, v in subs.items() if v]


def get_event_marker(game_id: int, event_key: str) -> int:
    data = _load()
    events = data.get("events", {}) or {}
    game_events = events.get(str(int(game_id)), {}) or {}
    try:
        return int(game_events.get(str(event_key), 0) or 0)
    except Exception:
        return 0


def set_event_marker(game_id: int, event_key: str, marker: int) -> None:
    data = _load()
    events = data.setdefault("events", {})
    g = str(int(game_id))
    game_events = events.get(g)
    if not isinstance(game_events, dict):
        game_events = {}
    game_events[str(event_key)] = int(marker)
    events[g] = game_events
    _save(data)


def get_meta_marker(key: str, default: str = "") -> str:
    data = _load()
    meta = data.get("meta", {}) or {}
    value = meta.get(str(key), default)
    if value is None:
        return default
    return str(value)


def set_meta_marker(key: str, value: str) -> None:
    data = _load()
    meta = data.setdefault("meta", {})
    meta[str(key)] = str(value)
    _save(data)
