import json
import logging
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from dotenv import load_dotenv

log = logging.getLogger(__name__)

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

# ---- Crypto deposits ----


def _safe_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    log.warning("%s is invalid; using default=%s", name, default)
    return default


def _safe_positive_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        log.warning("%s is invalid; using default=%s", name, default)
        return default
    if value < minimum:
        log.warning("%s is below %s; using default=%s", name, minimum, default)
        return default
    return value


def _safe_nonnegative_int(name: str, default: int) -> int:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        log.warning("%s is invalid; using default=%s", name, default)
        return default
    if value < 0:
        log.warning("%s must be non-negative; using default=%s", name, default)
        return default
    return value


def _safe_decimal(name: str, default: str) -> Decimal:
    raw = (os.getenv(name, "") or "").strip() or default
    try:
        value = Decimal(raw)
    except InvalidOperation:
        log.warning("%s is invalid; using default=%s", name, default)
        return Decimal(default)
    if value < 0:
        log.warning("%s must be non-negative; using default=%s", name, default)
        return Decimal(default)
    return value


CRYPTO_PAYMENTS_ENABLED = _safe_bool("CRYPTO_PAYMENTS_ENABLED", False)
CRYPTO_AUTO_CONFIRM_ENABLED = _safe_bool("CRYPTO_AUTO_CONFIRM_ENABLED", True)
CRYPTO_CONFIRM_INTERVAL_SEC = _safe_positive_int("CRYPTO_CONFIRM_INTERVAL_SEC", 45, minimum=10)
CRYPTO_INVOICE_EXPIRE_MINUTES = _safe_positive_int("CRYPTO_INVOICE_EXPIRE_MINUTES", 15, minimum=2)
CRYPTO_PAYMENT_GRACE_MINUTES = _safe_nonnegative_int("CRYPTO_PAYMENT_GRACE_MINUTES", 5)
CRYPTO_MIN_TOMAN_AMOUNT = _safe_positive_int("CRYPTO_MIN_TOMAN_AMOUNT", 50_000)
CRYPTO_MAX_TOMAN_AMOUNT = _safe_positive_int("CRYPTO_MAX_TOMAN_AMOUNT", 50_000_000)
CRYPTO_ADMIN_REVIEW_TOMAN_THRESHOLD = _safe_positive_int(
    "CRYPTO_ADMIN_REVIEW_TOMAN_THRESHOLD",
    20_000_000,
)
CRYPTO_RATE_PROVIDER_PRIMARY = (os.getenv("CRYPTO_RATE_PROVIDER_PRIMARY", "nobitex") or "nobitex").strip().lower()
CRYPTO_RATE_PROVIDER_FALLBACK = (os.getenv("CRYPTO_RATE_PROVIDER_FALLBACK", "wallex") or "wallex").strip().lower()
CRYPTO_RATE_FAIL_ALLOW_STALE_SEC = _safe_nonnegative_int("CRYPTO_RATE_FAIL_ALLOW_STALE_SEC", 0)
CRYPTO_RATE_MAX_DEVIATION_PERCENT = _safe_decimal("CRYPTO_RATE_MAX_DEVIATION_PERCENT", "8")
CRYPTO_RATE_BUFFER_PERCENT = _safe_decimal("CRYPTO_RATE_BUFFER_PERCENT", "0")
CRYPTO_HTTP_TIMEOUT_SEC = _safe_positive_int("CRYPTO_HTTP_TIMEOUT_SEC", 12, minimum=3)
CRYPTO_SCAN_LOOKBACK_HOURS = _safe_positive_int("CRYPTO_SCAN_LOOKBACK_HOURS", 24, minimum=1)
CRYPTO_PENDING_ALERT_MINUTES = _safe_positive_int("CRYPTO_PENDING_ALERT_MINUTES", 10, minimum=2)
CRYPTO_DAILY_USER_MAX_COUNT = _safe_nonnegative_int("CRYPTO_DAILY_USER_MAX_COUNT", 5)
CRYPTO_DAILY_USER_MAX_TOMAN = _safe_nonnegative_int("CRYPTO_DAILY_USER_MAX_TOMAN", 100_000_000)
CRYPTO_DAILY_TIMEZONE = (os.getenv("CRYPTO_DAILY_TIMEZONE", "Asia/Tehran") or "Asia/Tehran").strip()
CRYPTO_RECONCILIATION_LOOKBACK_HOURS = _safe_positive_int(
    "CRYPTO_RECONCILIATION_LOOKBACK_HOURS",
    24,
    minimum=1,
)

CRYPTO_NOBITEX_BASE_URL = (
    os.getenv("CRYPTO_NOBITEX_BASE_URL", "https://api.nobitex.ir") or "https://api.nobitex.ir"
).strip().rstrip("/")
CRYPTO_WALLEX_BASE_URL = (
    os.getenv("CRYPTO_WALLEX_BASE_URL", "https://api.wallex.ir") or "https://api.wallex.ir"
).strip().rstrip("/")

CRYPTO_TRON_USDT_ENABLED = _safe_bool("CRYPTO_TRON_USDT_ENABLED", True)
CRYPTO_TRON_USDT_ADDRESS = (os.getenv("CRYPTO_TRON_USDT_ADDRESS", "") or "").strip()
CRYPTO_TRON_USDT_CONTRACT = (
    os.getenv("CRYPTO_TRON_USDT_CONTRACT", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
    or "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
).strip()
CRYPTO_TRON_USDT_DECIMALS = _safe_positive_int("CRYPTO_TRON_USDT_DECIMALS", 6, minimum=1)
CRYPTO_TRONGRID_BASE_URL = (
    os.getenv("CRYPTO_TRONGRID_BASE_URL", "https://api.trongrid.io") or "https://api.trongrid.io"
).strip().rstrip("/")
TRONGRID_API_KEY = (os.getenv("TRONGRID_API_KEY", "") or "").strip()
CRYPTO_TRON_EXPLORER_TX_BASE = (
    os.getenv("CRYPTO_TRON_EXPLORER_TX_BASE", "https://tronscan.org/#/transaction")
    or "https://tronscan.org/#/transaction"
).strip().rstrip("/")

CRYPTO_TON_ENABLED = _safe_bool("CRYPTO_TON_ENABLED", True)
CRYPTO_TON_ADDRESS = (os.getenv("CRYPTO_TON_ADDRESS", "") or "").strip()
CRYPTO_TON_DECIMALS = _safe_positive_int("CRYPTO_TON_DECIMALS", 6, minimum=1)
CRYPTO_TONCENTER_BASE_URL = (
    os.getenv("CRYPTO_TONCENTER_BASE_URL", "https://toncenter.com") or "https://toncenter.com"
).strip().rstrip("/")
TONCENTER_API_KEY = (os.getenv("TONCENTER_API_KEY", "") or "").strip()
CRYPTO_TON_EXPLORER_TX_BASE = (
    os.getenv("CRYPTO_TON_EXPLORER_TX_BASE", "https://tonviewer.com/transaction")
    or "https://tonviewer.com/transaction"
).strip().rstrip("/")


def crypto_config_warnings() -> list[str]:
    warnings: list[str] = []
    if CRYPTO_MAX_TOMAN_AMOUNT < CRYPTO_MIN_TOMAN_AMOUNT:
        warnings.append("CRYPTO_MAX_TOMAN_AMOUNT is below CRYPTO_MIN_TOMAN_AMOUNT")
    if CRYPTO_TRON_USDT_ENABLED and not CRYPTO_TRON_USDT_ADDRESS:
        warnings.append("CRYPTO_TRON_USDT_ADDRESS is missing; TRON deposits are unavailable")
    elif CRYPTO_TRON_USDT_ENABLED and not re.fullmatch(
        r"T[1-9A-HJ-NP-Za-km-z]{33}",
        CRYPTO_TRON_USDT_ADDRESS,
    ):
        warnings.append("CRYPTO_TRON_USDT_ADDRESS is invalid; TRON deposits are unavailable")
    if CRYPTO_TRON_USDT_ENABLED and not re.fullmatch(
        r"T[1-9A-HJ-NP-Za-km-z]{33}",
        CRYPTO_TRON_USDT_CONTRACT,
    ):
        warnings.append("CRYPTO_TRON_USDT_CONTRACT is invalid; TRON deposits are unavailable")
    if CRYPTO_TON_ENABLED and not CRYPTO_TON_ADDRESS:
        warnings.append("CRYPTO_TON_ADDRESS is missing; TON deposits are unavailable")
    elif CRYPTO_TON_ENABLED and not (
        re.fullmatch(r"[A-Za-z0-9_-]{48}", CRYPTO_TON_ADDRESS)
        or re.fullmatch(r"-?\d+:[0-9A-Fa-f]{64}", CRYPTO_TON_ADDRESS)
    ):
        warnings.append("CRYPTO_TON_ADDRESS is invalid; TON deposits are unavailable")
    return warnings
