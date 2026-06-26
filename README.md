# Davarna Toofan

[فارسی](README.fa.md) · English

**Davarna Toofan** is a production-oriented Telegram Mini App and Telegram Bot platform for running Persian Bingo / Davarna games. It includes live game management, card purchasing, wallet accounting, bank-card deposits with receipt review, withdrawals, admin operations, notifications, and TON/TRON crypto deposit support.

> Persian brand: **دبرنای طوفان**  
> Internal project/repository name may still use `davarna` / `dabarna` for deployment compatibility.

---

## Table of Contents

- [Overview](#overview)
- [Core Features](#core-features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Repository Structure](#repository-structure)
- [Payment Flows](#payment-flows)
- [Admin and Super Admin](#admin-and-super-admin)
- [Local Development](#local-development)
- [Production Deployment](#production-deployment)
- [Environment Variables](#environment-variables)
- [Operations Checklist](#operations-checklist)
- [Security Notes](#security-notes)
- [Roadmap](#roadmap)
- [License](#license)

---

## Overview

Davarna Toofan is designed around Telegram-first gameplay:

1. A user opens the Telegram Bot or Mini App.
2. The user joins available games and buys cards from wallet balance.
3. Admins manage lobby state, start games, call numbers, and review finance operations.
4. The platform tracks wallet ledger entries, deposits, withdrawals, prizes, notifications, and audit events.
5. Crypto deposits can be issued as invoices and monitored through blockchain confirmation logic.

The project is built for private commercial operation, not as a generic public SaaS template.

---

## Core Features

### Telegram Mini App

- Mobile-first Persian UI
- Wallet balance and transaction history
- Active games and live game snapshot
- My cards preview
- Bank-card deposit form with receipt upload
- TON/TRON crypto deposit invoice flow
- Manual QR/address fallback for crypto payments
- Optional transaction hash submission
- Admin panel inside Mini App
- Super-admin controls for crypto payment runtime status

### Telegram Bot

- User onboarding and menu flow
- Wallet, deposit, withdraw, game, and card actions
- Join-gate support
- Admin finance alerts
- Admin game management
- Admin user management
- Super-admin role and bank-card destination management
- Notification worker for game/user events

### Backend

- FastAPI API layer
- MySQL persistence
- Redis support
- Wallet ledger model
- Game and card purchase services
- Finance request approval/rejection flows
- Crypto invoice, preflight, QR, health, reconciliation, and worker services
- Admin RBAC and audit logs
- Static serving for the Telegram Mini App

---

## Architecture

```text
Telegram User
   │
   ├── Telegram Bot
   │      └── Aiogram routers, FSM, notification worker
   │
   └── Telegram Mini App
          └── HTML/CSS/JS frontend
                    │
                    ▼
              FastAPI Backend
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
      MySQL       Redis      Storage
        │                       │
        ▼                       ▼
 Wallet / Game / Finance     Receipts
 Crypto / Admin / Audit
```

### Runtime services

```text
davarna-mysql      MySQL 8.0 database
davarna-redis      Redis 7 cache/queue support
davarna-backend    FastAPI backend + Mini App static files + crypto worker
davarna-bot        Telegram bot
davarna-nginx      Optional edge reverse proxy profile
certbot            Optional TLS certificate helper profile
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI |
| ORM / DB | SQLAlchemy, Alembic, MySQL 8 |
| Bot | Aiogram 3 |
| Cache / Queue | Redis |
| Mini App | HTML, CSS, Vanilla JavaScript |
| Crypto frontend bundle | esbuild, TON Connect, WalletConnect/TRON tooling |
| Deployment | Docker Compose |
| Runtime | Python 3.13 containers |
| Reverse Proxy | Optional Nginx profile |

---

## Repository Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── core/               # Configuration, DB, admin guards, Mini App security
│   │   ├── models/             # SQLAlchemy models
│   │   ├── routers/            # FastAPI routers
│   │   ├── schemas/            # Pydantic schemas
│   │   ├── services/           # Business logic
│   │   ├── scripts/            # Seed and maintenance scripts
│   │   └── static/mini/        # Built Telegram Mini App
│   ├── frontend/               # Wallet/crypto checkout frontend bundle
│   ├── alembic/                # Database migrations
│   ├── Dockerfile
│   └── requirements.txt
│
├── davarna-bot/
│   ├── bot/
│   │   ├── routers/            # Bot feature routers
│   │   ├── keyboards/          # Inline keyboards
│   │   ├── middlewares/        # User/API/throttling middleware
│   │   ├── services/           # API client, notifier helpers, Telegram helpers
│   │   ├── states/             # FSM states
│   │   └── workers/            # Notification worker
│   ├── Dockerfile
│   └── requirements.txt
│
├── deploy/                     # Nginx / Certbot deployment assets
├── storage/                    # Runtime storage, not for Git
└── docker-compose.yml
```

---

## Payment Flows

### Bank-card deposit

```text
User selects a bank destination
→ User enters amount
→ User transfers money manually
→ User uploads receipt
→ Admin reviews and approves/rejects
→ Approved amount is credited to wallet ledger
```

Supported bank destination management:

- Multiple bank cards
- Per-card active/inactive state
- Super-admin add/edit/delete flow
- Runtime bank-card deposit toggle can be added/managed through the super-admin Mini App flow

### Crypto deposit

```text
User selects crypto network
→ Backend creates invoice using live rate
→ User pays by direct wallet flow or manual QR/address copy
→ Worker/preflight services monitor the network
→ User may submit transaction hash
→ Backend credits wallet after confirmation
```

Supported crypto concepts:

- TON
- TRON / USDT TRC20
- Invoice expiration
- Network fee guidance
- QR fallback
- Explorer links
- Admin review for special cases
- Health check and reconciliation tooling
- Runtime enable/disable control for super-admin

---

## Admin and Super Admin

### Admin capabilities

- Create and manage games
- Start games and call numbers
- Undo last called number
- Close lobby before game start
- Review bank deposits
- Review withdrawals
- Inspect user financial/game history
- Send user notifications
- Manage live links

### Super-admin capabilities

- Manage admin roles
- Manage bank-card destinations
- Toggle crypto deposit availability from Mini App
- Run crypto health checks
- Run crypto reconciliation
- Maintain high-risk operational settings

---

## Local Development

### 1. Clone

```bash
git clone <repository-url>
cd dabarna
```

### 2. Create environment files

Create the backend environment file:

```bash
cp .env.example .env
```

Create the bot environment file:

```bash
cp davarna-bot/.env.example davarna-bot/.env
```

If example files do not exist yet, create them from your production template without real secrets.

### 3. Start services

```bash
docker compose up -d --build
```

### 4. Check health

```bash
curl http://127.0.0.1:18080/health/db
```

Expected response:

```json
{"ok": true}
```

### 5. View logs

```bash
docker compose logs backend --tail=120
docker compose logs bot --tail=120
```

---

## Production Deployment

### Standard deployment

```bash
cd /opt/davarna

git pull origin main

docker compose --env-file .env.prod up -d --build

curl -sS http://127.0.0.1:18080/health/db
echo

docker compose --env-file .env.prod ps
```

### Backend-only rebuild

Use this when only backend, Mini App static files, routers, services, or configuration code changed:

```bash
cd /opt/davarna

git pull origin main

docker compose --env-file .env.prod up -d --build backend

curl -sS http://127.0.0.1:18080/health/db
echo

docker compose --env-file .env.prod ps
```

### Bot-only rebuild

Use this when only `davarna-bot/` changed:

```bash
cd /opt/davarna

git pull origin main

docker compose --env-file .env.prod up -d --build bot

docker compose --env-file .env.prod logs bot --tail=120
```

### Full logs

```bash
docker compose --env-file .env.prod logs backend --tail=150
docker compose --env-file .env.prod logs bot --tail=150
docker compose --env-file .env.prod logs mysql --tail=80
docker compose --env-file .env.prod logs redis --tail=80
```

---

## Environment Variables

Never commit real `.env`, `.env.prod`, bot tokens, admin tokens, private keys, seed phrases, or wallet secrets.

### Backend essentials

```env
DATABASE_URL=
REDIS_URL=

ADMIN_AUTH_ENABLED=true
ADMIN_AUTH_HEADER=X-Admin-Token
ADMIN_TOKENS=
SUPER_ADMIN_TOKENS=
ADMIN_TOKEN_MAP=
ADMIN_TOKEN_ROLE_MAP=
ADMIN_TG_USER_IDS=
SUPER_ADMIN_TG_USER_IDS=
RBAC_OWNER_USER_ID=

BOT_SERVICE_TOKEN=
BOT_SERVICE_USER_ID=999

TELEGRAM_BOT_TOKEN=
TELEGRAM_INITDATA_MAX_AGE_SECONDS=86400
TELEGRAM_INITDATA_HEADER=X-Tg-Init-Data

MINI_SESSION_SECRET=
MINI_SESSION_TTL_SEC=900
MINI_INITDATA_REPLAY_TTL_SEC=900
MINI_RATE_LIMIT_EVENTS_PER_SEC=2
MINI_RATE_LIMIT_WRITE_PER_MIN=20

DEFAULT_TG_GROUP_ID=
USER_FORUM_CHAT_ID=
USER_TOPIC_GAME_LOW_ID=
USER_TOPIC_GAME_MEDIUM_ID=
USER_TOPIC_GAME_HIGH_ID=

RECEIPTS_DIR=/app/storage/receipts
CORS_ALLOWED_ORIGINS=
```

### Bank-card deposits

Prefer DB-managed bank destinations in production. Use `.env.prod` only as fallback/bootstrap.

```env
DEPOSIT_DESTINATION_SALT=davarna-pool-v1
DEPOSIT_DESTINATIONS_JSON=[]

DEPOSIT_CARD_NUMBER=
DEPOSIT_OWNER_NAME=
DEPOSIT_BANK_NAME=
DEPOSIT_IBAN=
DEPOSIT_ACCOUNT_NUMBER=
```

### Crypto deposits

```env
CRYPTO_PAYMENTS_ENABLED=false
CRYPTO_AUTO_CONFIRM_ENABLED=true
CRYPTO_CONFIRM_INTERVAL_SEC=45
CRYPTO_INVOICE_EXPIRE_MINUTES=15
CRYPTO_PAYMENT_GRACE_MINUTES=5

CRYPTO_MIN_TOMAN_AMOUNT=50000
CRYPTO_MAX_TOMAN_AMOUNT=50000000
CRYPTO_ADMIN_REVIEW_TOMAN_THRESHOLD=20000000

CRYPTO_DIRECT_WALLET_PAYMENTS_ENABLED=true
CRYPTO_WALLETCONNECT_PROJECT_ID=
CRYPTO_PUBLIC_APP_URL=

CRYPTO_TRON_USDT_ENABLED=true
CRYPTO_TRON_USDT_ADDRESS=
CRYPTO_TRON_USDT_CONTRACT=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t
CRYPTO_TRONGRID_BASE_URL=https://api.trongrid.io
TRONGRID_API_KEY=

CRYPTO_TON_ENABLED=true
CRYPTO_TON_ADDRESS=
CRYPTO_TONCENTER_BASE_URL=https://toncenter.com
TONCENTER_API_KEY=
```

### Bot essentials

```env
TELEGRAM_BOT_TOKEN=
API_BASE_URL=http://backend:8000
REDIS_URL=redis://redis:6379/0

BOT_SERVICE_TOKEN=
ADMIN_API_TOKEN=
SUPER_ADMIN_API_TOKEN=

ADMIN_TG_USER_IDS=
SUPER_ADMIN_TG_USER_IDS=

BOT_JOIN_GROUP_ID=
BOT_JOIN_GROUP_INVITE_LINK=

ADMIN_FORUM_CHAT_ID=
ADMIN_TOPIC_GENERAL_ID=
ADMIN_TOPIC_DEPOSIT_ID=
ADMIN_TOPIC_WITHDRAW_ID=
ADMIN_TOPIC_GAMES_ID=
ADMIN_TOPIC_ALERTS_ID=
ADMIN_TOPIC_USERS_ID=

USER_FORUM_CHAT_ID=
USER_TOPIC_ANNOUNCE_ID=
USER_TOPIC_GAME_LOW_ID=
USER_TOPIC_GAME_MEDIUM_ID=
USER_TOPIC_GAME_HIGH_ID=
USER_TOPIC_LIVE_NUMBERS_ID=
USER_TOPIC_RESULTS_ID=
USER_TOPIC_RULES_ID=
USER_TOPIC_CHAT_ID=
```

---

## Operations Checklist

### After every deployment

```bash
curl -sS http://127.0.0.1:18080/health/db
docker compose --env-file .env.prod ps
docker compose --env-file .env.prod logs backend --tail=80
docker compose --env-file .env.prod logs bot --tail=80
```

### Check bank destination source

```bash
docker compose --env-file .env.prod exec -T backend python - <<'PY'
from app.core.db import SessionLocal
from app.models.settings import AppSetting

with SessionLocal() as db:
    row = db.get(AppSetting, "deposit_destinations")
    if not row:
        print("DB deposit_destinations = NOT SET")
    else:
        items = row.v_json if isinstance(row.v_json, list) else []
        print("DB deposit_destinations_count =", len(items))
        for i, d in enumerate(items, 1):
            card = ''.join(ch for ch in str(d.get("card_number", "")) if ch.isdigit())
            masked = card[:4] + "-" + "*" * max(0, len(card)-8) + "-" + card[-4:] if len(card) >= 8 else "-"
            print(i, d.get("title"), d.get("bank_name"), d.get("account_name"), masked, "active=", d.get("is_active", True))
PY
```

### Check backend env fallback bank destinations

```bash
docker compose --env-file .env.prod exec -T backend python - <<'PY'
from app.core.config import DEPOSIT_DESTINATIONS, DEPOSIT_CARD_NUMBER

def mask(card):
    s = ''.join(ch for ch in str(card or '') if ch.isdigit())
    if len(s) < 8:
        return "-"
    return s[:4] + "-" + "*" * max(0, len(s)-8) + "-" + s[-4:]

print("env_json_destinations_count =", len(DEPOSIT_DESTINATIONS or []))
for i, d in enumerate(DEPOSIT_DESTINATIONS or [], 1):
    print(i, d.get("bank_name"), d.get("account_name"), mask(d.get("card_number")))

print("single_fallback_card =", mask(DEPOSIT_CARD_NUMBER))
PY
```

---

## Security Notes

- Keep repository private unless the product is intentionally open-sourced.
- Do not commit `.env`, `.env.prod`, real tokens, wallet addresses intended to remain private, API keys, or receipt files.
- Use strong `MINI_SESSION_SECRET`, admin tokens, and bot service tokens.
- Use HTTPS in production.
- Keep `RECEIPTS_DIR` outside public static paths.
- Treat receipt files and wallet history as private financial data.
- Keep admin and super-admin roles limited.
- Review `app_settings` changes through audit logs.
- Do not store wallet seed phrases or private keys in the app.
- Crypto verification should remain server-side.
- Bank deposit approval should remain auditable and reversible only through controlled wallet ledger operations.

---

## Recommended GitHub Repository Settings

### Description

```text
Telegram Mini App and Bot platform for Persian Davarna/Bingo games with wallet, admin controls, bank deposits, and crypto payments.
```

### Topics

```text
telegram-bot
telegram-mini-app
fastapi
aiogram
mysql
redis
docker
crypto-payments
ton
tron
bingo-game
wallet
admin-dashboard
```

### Suggested files

```text
README.md
README.fa.md
.env.example
.gitignore
docs/
docs/screenshots/
docs/deployment.md
docs/security.md
```

---

## Roadmap

- [x] Telegram Bot
- [x] Telegram Mini App
- [x] Wallet ledger
- [x] Card purchase flow
- [x] Bank-card deposit with receipt review
- [x] Withdrawal request flow
- [x] Admin game management
- [x] Super-admin role management
- [x] Multiple bank-card destinations
- [x] TON/TRON crypto invoice flow
- [x] Crypto QR/manual fallback
- [x] Crypto runtime toggle
- [ ] Bank-card runtime toggle in Mini App super-admin panel
- [ ] CI workflow for compile/test checks
- [ ] Screenshot gallery
- [ ] Complete operations documentation
- [ ] Automated backup documentation

---

## License

This project is proprietary. All rights reserved unless a separate license file states otherwise.
