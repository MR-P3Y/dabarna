from __future__ import annotations

import json
from pathlib import Path

from bot.config import settings

_STORE_PATH = Path("storage/admin_acl.json")


def _load_acl() -> tuple[set[int], set[int], dict[int, str]]:
    if not _STORE_PATH.exists():
        return set(), set(), {}
    try:
        data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return set(), set(), {}
        raw_dynamic = data.get("dynamic_admin_ids", [])
        raw_blocked = data.get("blocked_admin_ids", [])
        raw_labels = data.get("admin_labels", {})
        if not isinstance(raw_dynamic, list):
            raw_dynamic = []
        if not isinstance(raw_blocked, list):
            raw_blocked = []
        if not isinstance(raw_labels, dict):
            raw_labels = {}
        dynamic = {int(x) for x in raw_dynamic if str(x).isdigit()}
        blocked = {int(x) for x in raw_blocked if str(x).isdigit()}
        labels: dict[int, str] = {}
        for k, v in raw_labels.items():
            if not str(k).isdigit():
                continue
            val = str(v or "").strip()
            if not val:
                continue
            labels[int(k)] = val
        return dynamic, blocked, labels
    except Exception:
        return set(), set(), {}


def _save_acl(dynamic_ids: set[int], blocked_ids: set[int], labels: dict[int, str]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dynamic_admin_ids": sorted(int(x) for x in dynamic_ids if int(x) > 0),
        "blocked_admin_ids": sorted(int(x) for x in blocked_ids if int(x) > 0),
        "admin_labels": {str(int(k)): str(v) for k, v in sorted(labels.items()) if int(k) > 0 and str(v or "").strip()},
    }
    _STORE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_dynamic_admin_ids() -> set[int]:
    dynamic, _, _ = _load_acl()
    return dynamic


def get_blocked_admin_ids() -> set[int]:
    _, blocked, _ = _load_acl()
    return blocked


def list_all_admin_ids() -> set[int]:
    ids = set(settings.admin_ids)
    ids.update(settings.super_admin_ids)
    ids.update(get_dynamic_admin_ids())
    return ids


def is_admin_user(tg_user_id: int) -> bool:
    uid = int(tg_user_id)
    if uid in settings.super_admin_ids:
        return True
    blocked = get_blocked_admin_ids()
    if uid in blocked:
        return False
    if uid in settings.admin_ids:
        return True
    return uid in get_dynamic_admin_ids()


def is_super_admin_user(tg_user_id: int) -> bool:
    owner_id = settings.owner_super_admin_id
    if owner_id is not None:
        return int(tg_user_id) == int(owner_id)
    return int(tg_user_id) in settings.super_admin_ids


def grant_dynamic_admin(tg_user_id: int) -> None:
    uid = int(tg_user_id)
    dynamic, blocked, labels = _load_acl()
    blocked.discard(uid)
    if uid not in settings.admin_ids and uid not in settings.super_admin_ids:
        dynamic.add(uid)
    _save_acl(dynamic, blocked, labels)


def revoke_dynamic_admin(tg_user_id: int) -> None:
    uid = int(tg_user_id)
    if uid in settings.super_admin_ids:
        return
    dynamic, blocked, labels = _load_acl()
    dynamic.discard(uid)
    if uid in settings.admin_ids:
        blocked.add(uid)
    else:
        blocked.discard(uid)
    labels.pop(uid, None)
    _save_acl(dynamic, blocked, labels)


def sync_dynamic_admin_ids(tg_user_ids: set[int]) -> None:
    backend_ids = {int(x) for x in tg_user_ids if int(x) > 0}
    static_admins = set(settings.admin_ids)
    super_admins = set(settings.super_admin_ids)

    _, _, labels = _load_acl()
    dynamic = {uid for uid in backend_ids if uid not in static_admins and uid not in super_admins}
    blocked = {uid for uid in static_admins if uid not in backend_ids}
    keep_ids = backend_ids | super_admins
    clean_labels = {uid: val for uid, val in labels.items() if uid in keep_ids and str(val or "").strip()}
    _save_acl(dynamic, blocked, clean_labels)


def set_admin_label(tg_user_id: int, label: str) -> None:
    uid = int(tg_user_id)
    dynamic, blocked, labels = _load_acl()
    val = str(label or "").strip()
    if val:
        labels[uid] = val
    else:
        labels.pop(uid, None)
    _save_acl(dynamic, blocked, labels)


def get_admin_label(tg_user_id: int) -> str:
    _, _, labels = _load_acl()
    return str(labels.get(int(tg_user_id), "") or "")
