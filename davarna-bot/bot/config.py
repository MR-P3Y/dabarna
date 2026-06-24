from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]  # davarna-bot/

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        extra="ignore",
    )
    ADMIN_API_TOKEN: str | None = None
    SUPER_ADMIN_API_TOKEN: str | None = None
    ADMIN_TG_USER_IDS: str | None = None
    SUPER_ADMIN_TG_USER_IDS: str | None = None
    TELEGRAM_BOT_TOKEN: str
    API_BASE_URL: str = "http://127.0.0.1:8000"
    REDIS_URL: str = "redis://localhost:6381/0"
    BOT_SERVICE_TOKEN: str | None = None
    BOT_JOIN_GROUP_ID: int | None = None
    BOT_JOIN_GROUP_INVITE_LINK: str | None = None
    ADMIN_FORUM_CHAT_ID: int | None = None
    ADMIN_TOPIC_GENERAL_ID: int | None = None
    ADMIN_TOPIC_WINNERS_ID: int | None = None
    ADMIN_TOPIC_WITHDRAW_ID: int | None = None
    ADMIN_TOPIC_DEPOSIT_ID: int | None = None
    ADMIN_TOPIC_INCOME_ID: int | None = None
    ADMIN_TOPIC_GAMES_ID: int | None = None
    ADMIN_TOPIC_ALERTS_ID: int | None = None
    ADMIN_TOPIC_ANTIFRAUD_ID: int | None = None
    ADMIN_TOPIC_GAME_AUDIT_ID: int | None = None
    ADMIN_TOPIC_USERS_ID: int | None = None
    ADMIN_TOPIC_ENABLE_DM_FALLBACK: bool = True
    ADMIN_TOPIC_SLA_MINUTES: int = 30
    ADMIN_TOPIC_AUDIT_INTERVAL_SEC: int = 120
    ADMIN_TOPIC_DAILY_SUMMARY_HOUR_UTC: int = 18
    ADMIN_TOPIC_DAILY_REVENUE_HOUR_LOCAL: int = 15
    ADMIN_TOPIC_TIMEZONE: str = "Asia/Tehran"
    ADMIN_TOPIC_AUTO_PIN_RULES: bool = True
    ADMIN_CRYPTO_HEALTH_INTERVAL_SEC: int = 300
    ADMIN_CRYPTO_RECONCILIATION_HOUR_LOCAL: int = 16
    USER_FORUM_CHAT_ID: int | None = None
    USER_TOPIC_ANNOUNCE_ID: int | None = None
    USER_TOPIC_GAME_LOW_ID: int | None = None
    USER_TOPIC_GAME_MEDIUM_ID: int | None = None
    USER_TOPIC_GAME_HIGH_ID: int | None = None
    USER_TOPIC_LIVE_NUMBERS_ID: int | None = None
    USER_TOPIC_RESULTS_ID: int | None = None
    USER_TOPIC_RULES_ID: int | None = None
    USER_TOPIC_CHAT_ID: int | None = None
    NOTIFIER_INTERVAL_SEC: float = 2.0
    NOTIFIER_LAST_N: int = 200
    NOTIFIER_SEND_WORKERS: int = 2
    NOTIFIER_SEND_WORKERS_MAX: int = 3
    NOTIFIER_SEND_DELAY_SEC: float = 0.025
    NOTIFIER_QUEUE_MAXSIZE: int = 5000
    NOTIFIER_DEAD_FAIL_THRESHOLD: int = 3
    NOTIFIER_EVENTS_LIMIT_FAST: int = 100
    NOTIFIER_FAST_GAMES_LIMIT: int = 120
    NOTIFIER_HEAVY_INTERVAL_SEC: float = 30.0
    NOTIFIER_EVENTS_LIMIT_SLOW: int = 150
    NOTIFIER_SLOW_GAMES_LIMIT: int = 80
    NOTIFIER_HOT_GAME_TTL_SEC: float = 120.0
    NOTIFIER_ADAPTIVE_CHECK_SEC: float = 180.0
    NOTIFIER_ADAPTIVE_MIN_JOBS: int = 120
    NOTIFIER_METRICS_REPORT_SEC: float = 60.0

    @property
    def admin_ids(self) -> set[int]:
        if not self.ADMIN_TG_USER_IDS:
            return set()
        return {int(x.strip()) for x in self.ADMIN_TG_USER_IDS.split(",") if x.strip().isdigit()}

    @property
    def super_admin_ids(self) -> set[int]:
        if not self.SUPER_ADMIN_TG_USER_IDS:
            return set()
        return {int(x.strip()) for x in self.SUPER_ADMIN_TG_USER_IDS.split(",") if x.strip().isdigit()}

    @property
    def owner_super_admin_id(self) -> int | None:
        if not self.SUPER_ADMIN_TG_USER_IDS:
            return None
        for raw in self.SUPER_ADMIN_TG_USER_IDS.split(","):
            value = raw.strip()
            if value.isdigit():
                return int(value)
        return None
settings = Settings()
