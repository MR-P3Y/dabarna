import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Header
from sqlalchemy import text
from app.core.db import engine
from app.core import config as cfg
from app.routers.user_router import router as user_router
from app.routers.wallet_router import router as wallet_router
from app.routers.finance_router import router as finance_router
from app.routers.game_router import router as game_router
from app.routers.admin_reports_router import router as admin_reports_router
from app.routers.settings_router import router as admin_settings_router
from app.core.config import ADMIN_AUTH_ENABLED, ADMIN_AUTH_HEADER, ADMIN_TOKEN_MAP, SUPER_ADMIN_TOKEN, ADMIN_TOKENS
from app.routers.admin_events_router import router as admin_events_router
from app.routers.admin_whoami_router import router as admin_whoami_router
from app.routers.admin_rbac_router import router as admin_rbac_router
from app.routers.tg_router import router as tg_router
from app.routers.auth_router import router as auth_router
from app.routers.bot_router import router as bot_router
from app.routers.admin_users_router import router as admin_users_router
from app.routers.mini_router import router as mini_router
from app.routers.admin_audit_router import router as admin_audit_router
from app.routers.crypto_router import router as crypto_router
from app.services.crypto_deposit_service import CryptoDepositService
from app.services.crypto_worker import run_crypto_worker_forever

from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event = asyncio.Event()
    task: asyncio.Task | None = None
    if cfg.CRYPTO_PAYMENTS_ENABLED:
        for warning in cfg.crypto_config_warnings():
            log.warning("crypto configuration: %s", warning)
        if cfg.CRYPTO_AUTO_CONFIRM_ENABLED and CryptoDepositService.configured_options():
            task = asyncio.create_task(
                run_crypto_worker_forever(stop_event),
                name="crypto-deposit-worker",
            )
            app.state.crypto_worker_task = task
    try:
        yield
    finally:
        stop_event.set()
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=5)
            except asyncio.TimeoutError:
                task.cancel()
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Davarna API", lifespan=lifespan)
_default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.CORS_ALLOWED_ORIGINS or _default_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(user_router)
app.include_router(wallet_router)
app.include_router(finance_router)
app.include_router(game_router)
app.include_router(admin_reports_router)
app.include_router(admin_settings_router)
app.include_router(admin_events_router)
app.include_router(admin_whoami_router)
app.include_router(admin_rbac_router)
app.include_router(tg_router)
app.include_router(auth_router)
app.include_router(bot_router)
app.include_router(admin_users_router)
app.include_router(mini_router)
app.include_router(admin_audit_router)
app.include_router(crypto_router)

mini_dir = Path(__file__).resolve().parent / "static" / "mini"
if mini_dir.exists():
    app.mount("/mini", StaticFiles(directory=str(mini_dir), html=True), name="mini")



def debug_admin_env():
    return {
        "enabled": ADMIN_AUTH_ENABLED,
        "header": ADMIN_AUTH_HEADER,
        "super_admin_token_set": bool(SUPER_ADMIN_TOKEN),
        "admin_tokens_count": len(ADMIN_TOKENS),
    }


@app.get("/health/db")
def health_db():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}



@app.get("/health/settings")
def health_settings():
    with engine.connect() as conn:
        res = conn.execute(text("SELECT COUNT(*) AS c FROM app_settings")).mappings().first()
    return {"settings_rows": int(res["c"])}


from app.core.config import REDIS_URL

def debug_redis():
    return {"redis_url": REDIS_URL}

def debug_admin_whoami(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")):
    tok = (x_admin_token or "").strip()
    return {
        "got_header": bool(tok),
        "token_last4": tok[-4:] if tok else None,
        "super_token_last4": SUPER_ADMIN_TOKEN[-4:] if SUPER_ADMIN_TOKEN else None,
        "is_super": bool(SUPER_ADMIN_TOKEN) and tok == SUPER_ADMIN_TOKEN,
        "mapped_user_id": ADMIN_TOKEN_MAP.get(tok),
    }
def debug_admin_sources():
    import os
    from app.core import config
    from app.models import settings
    return {
        "os_SUPER_ADMIN_TOKENS": os.getenv("SUPER_ADMIN_TOKENS"),
        "config_SUPER_ADMIN_TOKENS": sorted(list(getattr(config, "SUPER_ADMIN_TOKENS", []))),
        "settings_SUPER_ADMIN_TOKENS": sorted(list(getattr(settings, "SUPER_ADMIN_TOKENS", []))),
        "os_ADMIN_TOKEN_MAP": os.getenv("ADMIN_TOKEN_MAP"),
        "config_ADMIN_TOKEN_MAP": getattr(config, "ADMIN_TOKEN_MAP", {}),
    }
