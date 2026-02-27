import json
import os
from pathlib import Path
from dotenv import load_dotenv

# مسیر فایل: ...\backend\app\core\config.py
CORE_DIR = Path(__file__).resolve().parent          # ...\backend\app\core
APP_DIR = CORE_DIR.parent                           # ...\backend\app
BACKEND_DIR = APP_DIR.parent                        # ...\backend
ROOT_DIR = BACKEND_DIR.parent                       # ...\davarna

# اول تلاش کن .env داخل backend را بخوانی، اگر نبود از root بخوان
env_backend = BACKEND_DIR / ".env"
env_root = ROOT_DIR / ".env"

loaded = False
if env_backend.exists():
    # Force values from .env file to avoid stale process-level env vars.
    load_dotenv(env_backend, override=True)
    loaded = True
elif env_root.exists():
    # Force values from .env file to avoid stale process-level env vars.
    load_dotenv(env_root, override=True)
    loaded = True

DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")
if not REDIS_URL:
    raise RuntimeError("REDIS_URL is not set")

# ---- Admin auth ----
ADMIN_AUTH_ENABLED = os.getenv("ADMIN_AUTH_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ADMIN_AUTH_HEADER = os.getenv("ADMIN_AUTH_HEADER", "X-Admin-Token")
SUPER_ADMIN_TOKENS_RAW = os.getenv("SUPER_ADMIN_TOKENS", "").strip()
SUPER_ADMIN_TOKENS = [t.strip() for t in SUPER_ADMIN_TOKENS_RAW.split(",") if t.strip()]
SUPER_ADMIN_TOKEN = SUPER_ADMIN_TOKENS[0] if SUPER_ADMIN_TOKENS else ""
ADMIN_TOKENS = [t.strip() for t in os.getenv("ADMIN_TOKENS", "").split(",") if t.strip()]
ADMIN_TOKEN_MAP_RAW = os.getenv("ADMIN_TOKEN_MAP", "").strip()



def _parse_token_map(raw: str) -> dict[str, int]:
    m: dict[str, int] = {}
    if not raw:
        return m
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    for p in parts:
        if ":" not in p:
            continue
        token, uid = p.split(":", 1)
        token = token.strip()
        uid = uid.strip()
        if token and uid.isdigit():
            m[token] = int(uid)
    return m

ADMIN_TOKEN_MAP = _parse_token_map(ADMIN_TOKEN_MAP_RAW)

def _parse_token_role_map(raw: str) -> dict[str, str]:
    m: dict[str, str] = {}
    if not raw:
        return m
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    for p in parts:
        if ":" not in p:
            continue
        token, role = p.split(":", 1)
        token = token.strip()
        role = role.strip()
        if token and role:
            m[token] = role
    return m

ADMIN_TOKEN_ROLE_MAP_RAW = os.getenv("ADMIN_TOKEN_ROLE_MAP", "").strip()
ADMIN_TOKEN_ROLE_MAP = _parse_token_role_map(ADMIN_TOKEN_ROLE_MAP_RAW)


def _parse_csv_int_set(raw: str | None) -> set[int]:
    out: set[int] = set()
    text = str(raw or "").strip()
    if not text:
        return out
    for part in text.split(","):
        value = part.strip()
        if not value or not value.isdigit():
            continue
        out.add(int(value))
    return out


ADMIN_TG_USER_IDS = _parse_csv_int_set(os.getenv("ADMIN_TG_USER_IDS", ""))
SUPER_ADMIN_TG_USER_IDS = _parse_csv_int_set(os.getenv("SUPER_ADMIN_TG_USER_IDS", ""))


def _resolve_rbac_owner_user_id() -> int | None:
    raw = (os.getenv("RBAC_OWNER_USER_ID", "") or "").strip()
    if raw:
        if not raw.isdigit():
            raise RuntimeError("RBAC_OWNER_USER_ID must be an integer")
        return int(raw)

    # Fallback 1: explicit SUPER_ADMIN_TOKENS list
    for token in SUPER_ADMIN_TOKENS:
        uid = ADMIN_TOKEN_MAP.get(token)
        if isinstance(uid, int) and uid > 0:
            return int(uid)

    # Fallback 2: any token marked SUPER_ADMIN in role map
    for token, role in ADMIN_TOKEN_ROLE_MAP.items():
        if str(role).strip().upper() != "SUPER_ADMIN":
            continue
        uid = ADMIN_TOKEN_MAP.get(token)
        if isinstance(uid, int) and uid > 0:
            return int(uid)

    return None


RBAC_OWNER_USER_ID = _resolve_rbac_owner_user_id()

# ---- Bot authentication ----
BOT_SERVICE_TOKEN = os.getenv("BOT_SERVICE_TOKEN", "").strip()
BOT_SERVICE_USER_ID = int(os.getenv("BOT_SERVICE_USER_ID", "999") or "999")


def _parse_optional_int(name: str) -> int | None:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer")


DEFAULT_TG_GROUP_ID = _parse_optional_int("DEFAULT_TG_GROUP_ID")
USER_FORUM_CHAT_ID = _parse_optional_int("USER_FORUM_CHAT_ID")
USER_TOPIC_GAME_LOW_ID = _parse_optional_int("USER_TOPIC_GAME_LOW_ID")
USER_TOPIC_GAME_MEDIUM_ID = _parse_optional_int("USER_TOPIC_GAME_MEDIUM_ID")
USER_TOPIC_GAME_HIGH_ID = _parse_optional_int("USER_TOPIC_GAME_HIGH_ID")

# ---- Telegram WebApp verification ----
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_INITDATA_MAX_AGE_SECONDS = int(os.getenv("TELEGRAM_INITDATA_MAX_AGE_SECONDS", "86400") or "86400")
TELEGRAM_INITDATA_HEADER = os.getenv("TELEGRAM_INITDATA_HEADER", "X-Tg-Init-Data").strip()

# ---- Deposit Configuration ----
DEPOSIT_CARD_NUMBER = os.getenv("DEPOSIT_CARD_NUMBER", "").strip()
DEPOSIT_OWNER_NAME = os.getenv("DEPOSIT_OWNER_NAME", "").strip()
DEPOSIT_BANK_NAME = os.getenv("DEPOSIT_BANK_NAME", "").strip()
DEPOSIT_IBAN = os.getenv("DEPOSIT_IBAN", "").strip()
DEPOSIT_ACCOUNT_NUMBER = os.getenv("DEPOSIT_ACCOUNT_NUMBER", "").strip()


def _clean_numeric(value: str | int | None) -> str:
    return str(value or "").strip().replace(" ", "").replace("-", "")


def _normalize_destination_item(item: dict[str, object], *, idx: int) -> dict[str, str]:
    card_number = _clean_numeric(item.get("card_number"))
    if not card_number:
        raise RuntimeError(f"DEPOSIT_DESTINATIONS_JSON[{idx}].card_number is required")
    if (not card_number.isdigit()) or len(card_number) < 16 or len(card_number) > 19:
        raise RuntimeError(f"DEPOSIT_DESTINATIONS_JSON[{idx}].card_number is invalid")
    return {
        "account_name": str(item.get("account_name") or "").strip(),
        "bank_name": str(item.get("bank_name") or "").strip(),
        "iban": str(item.get("iban") or "").strip().upper(),
        "card_number": card_number,
        "account_number": _clean_numeric(item.get("account_number")),
    }


def _parse_deposit_destinations(raw: str) -> list[dict[str, str]]:
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        arr = json.loads(text)
    except Exception as e:
        raise RuntimeError(f"DEPOSIT_DESTINATIONS_JSON is not valid JSON: {str(e)}")
    if not isinstance(arr, list):
        raise RuntimeError("DEPOSIT_DESTINATIONS_JSON must be a JSON array")

    out: list[dict[str, str]] = []
    for i, item in enumerate(arr):
        if not isinstance(item, dict):
            raise RuntimeError(f"DEPOSIT_DESTINATIONS_JSON[{i}] must be an object")
        out.append(_normalize_destination_item(item, idx=i))
    return out


DEPOSIT_DESTINATIONS_JSON = os.getenv("DEPOSIT_DESTINATIONS_JSON", "").strip()
DEPOSIT_DESTINATIONS = _parse_deposit_destinations(DEPOSIT_DESTINATIONS_JSON)
if not DEPOSIT_DESTINATIONS and DEPOSIT_CARD_NUMBER:
    DEPOSIT_DESTINATIONS = [
        _normalize_destination_item(
            {
                "account_name": DEPOSIT_OWNER_NAME,
                "bank_name": DEPOSIT_BANK_NAME,
                "iban": DEPOSIT_IBAN,
                "card_number": DEPOSIT_CARD_NUMBER,
                "account_number": DEPOSIT_ACCOUNT_NUMBER,
            },
            idx=0,
        )
    ]

DEPOSIT_DESTINATION_SALT = (os.getenv("DEPOSIT_DESTINATION_SALT", "davarna") or "davarna").strip() or "davarna"

# ---- Storage Configuration ----
RECEIPTS_DIR = Path(os.getenv("RECEIPTS_DIR", "./storage/receipts"))
RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

# ---- App / Frontend ----

def _parse_csv_list(raw: str | None) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    return [x.strip() for x in text.split(",") if x.strip()]


CORS_ALLOWED_ORIGINS = _parse_csv_list(os.getenv("CORS_ALLOWED_ORIGINS", ""))

# ---- Auth hardening ----
AUTH_DEBUG_ENABLED = os.getenv("AUTH_DEBUG_ENABLED", "false").lower() in ("1", "true", "yes", "on")

# ---- Mini App ----
MINI_SESSION_SECRET = (os.getenv("MINI_SESSION_SECRET", "") or "").strip() or "CHANGE_ME_MINI_SESSION_SECRET"
MINI_SESSION_TTL_SEC = int(os.getenv("MINI_SESSION_TTL_SEC", "900") or "900")
MINI_INITDATA_REPLAY_TTL_SEC = int(os.getenv("MINI_INITDATA_REPLAY_TTL_SEC", "900") or "900")
MINI_RATE_LIMIT_EVENTS_PER_SEC = int(os.getenv("MINI_RATE_LIMIT_EVENTS_PER_SEC", "2") or "2")
MINI_RATE_LIMIT_WRITE_PER_MIN = int(os.getenv("MINI_RATE_LIMIT_WRITE_PER_MIN", "20") or "20")
