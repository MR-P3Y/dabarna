from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl


@dataclass(frozen=True)
class TelegramWebAppInitData:
    raw: str
    data: dict[str, str]
    user: dict[str, Any] | None
    auth_date: int | None


class TelegramInitDataError(ValueError):
    pass


def parse_init_data(init_data: str) -> TelegramWebAppInitData:
    raw = (init_data or "").strip()
    if not raw:
        raise TelegramInitDataError("missing init_data")

    data = dict(parse_qsl(raw, keep_blank_values=True))
    user_obj = None
    auth_date = None

    if "user" in data and data["user"]:
        try:
            user_obj = json.loads(data["user"])
        except Exception as e:
            raise TelegramInitDataError("invalid user json") from e

    if "auth_date" in data and data["auth_date"]:
        try:
            auth_date = int(data["auth_date"])
        except Exception as e:
            raise TelegramInitDataError("invalid auth_date") from e

    return TelegramWebAppInitData(raw=raw, data=data, user=user_obj, auth_date=auth_date)


def verify_init_data(init_data: str, bot_token: str) -> TelegramWebAppInitData:
    """Verify Telegram WebApp initData signature (HMAC-SHA256).

    Docs: https://core.telegram.org/bots/webapps#validating-data-received-via-the-web-app
    """
    parsed = parse_init_data(init_data)
    data = parsed.data

    recv_hash = (data.get("hash") or "").strip()
    if not recv_hash:
        raise TelegramInitDataError("missing hash")

    # Build data_check_string
    pairs: list[str] = []
    for k, v in data.items():
        if k == "hash":
            continue
        pairs.append(f"{k}={v}")
    pairs.sort()
    data_check_string = "\n".join(pairs)

    # Telegram Mini App validation:
    # secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    # Constant-time compare
    if not hmac.compare_digest(calc_hash, recv_hash):
        raise TelegramInitDataError("invalid hash")

    return parsed


def verify_init_data_with_age(init_data: str, bot_token: str, max_age_seconds: int) -> TelegramWebAppInitData:
    parsed = verify_init_data(init_data, bot_token=bot_token)

    if parsed.auth_date is None:
        raise TelegramInitDataError("auth_date missing")

    if max_age_seconds > 0:
        import time
        now = int(time.time())
        age = now - int(parsed.auth_date)
        if age > int(max_age_seconds):
            raise TelegramInitDataError("auth_date too old")

    return parsed
