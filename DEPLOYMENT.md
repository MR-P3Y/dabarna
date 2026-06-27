# Davarna Deployment (Host Nginx + Docker Compose)

## 1) Production Environment Files

1. Fill `./.env.prod` (root env for backend/mysql/redis).
2. Fill `./davarna-bot/.env.prod` (bot runtime env).
3. Required keys in `.env.prod`:
- `NGINX_SERVER_NAME=davarna.peymoonnet.de`
- `BACKEND_HOST_PORT=18080`

## Crypto deposits

Crypto deposits are disabled by default. Enable them only after public receiving
addresses and read-only provider API keys are configured in `.env.prod`.
Private keys and seed phrases must never be stored in this project.

```env
CRYPTO_PAYMENTS_ENABLED=true
CRYPTO_AUTO_CONFIRM_ENABLED=true
CRYPTO_CONFIRM_INTERVAL_SEC=45
CRYPTO_INVOICE_EXPIRE_MINUTES=15
CRYPTO_PAYMENT_GRACE_MINUTES=5
CRYPTO_PENDING_ALERT_MINUTES=10
CRYPTO_SCAN_LOOKBACK_HOURS=24

CRYPTO_MIN_TOMAN_AMOUNT=50000
CRYPTO_MAX_TOMAN_AMOUNT=50000000
CRYPTO_ADMIN_REVIEW_TOMAN_THRESHOLD=20000000
CRYPTO_DAILY_USER_MAX_COUNT=5
CRYPTO_DAILY_USER_MAX_TOMAN=100000000
CRYPTO_DAILY_TIMEZONE=Asia/Tehran
CRYPTO_RECONCILIATION_LOOKBACK_HOURS=24
CRYPTO_PREFLIGHT_CACHE_SEC=30
CRYPTO_DIRECT_WALLET_PAYMENTS_ENABLED=true
CRYPTO_PUBLIC_APP_URL=https://davarna.peymoonnet.de
CRYPTO_WALLETCONNECT_PROJECT_ID=
CRYPTO_TRON_ESTIMATED_FEE_TRX=30
CRYPTO_TON_ESTIMATED_FEE_TON=0.01

CRYPTO_RATE_PROVIDER_PRIMARY=nobitex
CRYPTO_RATE_PROVIDER_FALLBACK=wallex
CRYPTO_RATE_FAIL_ALLOW_STALE_SEC=0
CRYPTO_RATE_MAX_DEVIATION_PERCENT=8
CRYPTO_RATE_BUFFER_PERCENT=0
CRYPTO_HTTP_TIMEOUT_SEC=12
CRYPTO_BINANCE_BASE_URL=https://data-api.binance.vision

CRYPTO_TRON_USDT_ENABLED=true
CRYPTO_TRON_USDT_ADDRESS=
CRYPTO_TRON_USDT_CONTRACT=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t
CRYPTO_TRON_USDT_DECIMALS=6
CRYPTO_TRONGRID_BASE_URL=https://api.trongrid.io
TRONGRID_API_KEY=
CRYPTO_TRON_EXPLORER_TX_BASE=https://tronscan.org/#/transaction

CRYPTO_TON_ENABLED=true
CRYPTO_TON_ADDRESS=
CRYPTO_TON_DECIMALS=9
CRYPTO_TONCENTER_BASE_URL=https://toncenter.com
TONCENTER_API_KEY=
CRYPTO_TON_EXPLORER_TX_BASE=https://tonviewer.com/transaction
```

`CRYPTO_TRON_USDT_ADDRESS` and `CRYPTO_TON_ADDRESS` are public receiving
addresses. Set them only in `.env.prod`; never enter a private key, recovery
phrase, or wallet password. `CRYPTO_PAYMENTS_ENABLED=true` is the server-side
master switch. After the backend restarts, the owner super admin can turn user
access on or off from the mini-app without another deployment. The first
runtime state is off until the super admin enables it.

`CRYPTO_WALLETCONNECT_PROJECT_ID` is the public project ID from the
WalletConnect dashboard. Add `https://davarna.peymoonnet.de` to that project's
origin allowlist. If it is empty, direct TRON wallet payment is disabled while
QR/copy payment remains available. TON Connect uses
`https://davarna.peymoonnet.de/tonconnect-manifest.json`.

Optional bot monitoring settings belong in `./davarna-bot/.env.prod`:

```env
ADMIN_CRYPTO_HEALTH_INTERVAL_SEC=300
ADMIN_CRYPTO_RECONCILIATION_HOUR_LOCAL=16
```

To configure the production files without printing wallet addresses or existing
secrets, pass the two public receiving addresses to the deployment helper:

```bash
cd /opt/davarna
chmod +x scripts/configure-crypto-env.sh

read -rsp "Public TRON address: " CRYPTO_TRON_USDT_ADDRESS; echo
read -rsp "Public TON address: " CRYPTO_TON_ADDRESS; echo
read -rsp "WalletConnect project ID (public): " CRYPTO_WALLETCONNECT_PROJECT_ID; echo
export CRYPTO_TRON_USDT_ADDRESS CRYPTO_TON_ADDRESS CRYPTO_WALLETCONNECT_PROJECT_ID

./scripts/configure-crypto-env.sh
unset CRYPTO_TRON_USDT_ADDRESS CRYPTO_TON_ADDRESS CRYPTO_WALLETCONNECT_PROJECT_ID
```

The helper creates timestamped backups, updates the backend and bot env files
idempotently, and never prints wallet addresses. Unreadable comments containing
`??` are replaced with an English comment. If an actual env value contains
`??`, the helper stops and prints only its key; fix that value in English before
running it again.

The backend fetches a live best-ask quote when each invoice is created, locks
the Toman and crypto amounts until expiry, scans confirmed/finalized incoming
transactions, and credits the wallet idempotently. Invoices at or above
`CRYPTO_ADMIN_REVIEW_TOMAN_THRESHOLD` require admin approval after chain
confirmation.
- `BACKUP_CHAT_ID=-100xxxxxxxxxx`
- `BACKUP_BOT_TOKEN=` (optional; empty means reuse `TELEGRAM_BOT_TOKEN`)

Required bot join-gate keys in `./davarna-bot/.env.prod`:
- `BOT_JOIN_GROUP_ID=-100xxxxxxxxxx`
- `BOT_JOIN_GROUP_INVITE_LINK=https://t.me/+xxxxxxxxxxxx`

For private groups, `BOT_JOIN_GROUP_INVITE_LINK` is required unless the bot is an admin with invite-link permission.

## 2) Start Stack (without dockerized nginx)

Project root:

```bash
docker compose --env-file .env.prod up -d --build mysql redis backend bot
```

Notes:
- `backend` is published only on `127.0.0.1:${BACKEND_HOST_PORT}`.
- `mysql` and `redis` are private (no public host ports).
- migrations run automatically inside backend container (`alembic upgrade head`).

## 3) Host Nginx vhost for `davarna.peymoonnet.de`

Use host nginx (recommended when same server already has n8n/x-ui):

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name davarna.peymoonnet.de;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name davarna.peymoonnet.de;

    ssl_certificate     /etc/ssl/davarna/fullchain.pem;
    ssl_certificate_key /etc/ssl/davarna/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_prefer_server_ciphers off;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options SAMEORIGIN always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:18080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 4) Scheduled Ops Tasks

1. DB backup مستقیم به تلگرام (بدون ذخیره روی سرور):

```bash
bash /opt/davarna/scripts/backup-db-to-telegram.sh
```

2. حذف رسیدهای قدیمی‌تر از ۵ روز:

```bash
bash /opt/davarna/scripts/cleanup-receipts.sh
```

3. مانیتورینگ و alert به تاپیک ادمین:

```bash
chmod +x /opt/davarna/scripts/davarna-monitor.sh
/opt/davarna/scripts/davarna-monitor.sh
```

مانیتور این موارد را چک می‌کند:
- containerهای `backend`, `bot`, `mysql`, `redis`
- health داخلی و عمومی دبرنای طوفان
- host nginx
- cron
- fail2ban
- disk usage
- وضعیت بکاپ تلگرام و بکاپ لوکال، اگر مسیر/لاگ آن تنظیم شده باشد

متغیرهای اختیاری در `.env.prod`:
- `MONITOR_ALERT_CHAT_ID` اگر تنظیم نشود از `ADMIN_FORUM_CHAT_ID` و بعد `BACKUP_CHAT_ID` استفاده می‌شود.
- `MONITOR_ALERT_TOPIC_ID` اگر تنظیم نشود از `ADMIN_TOPIC_ALERTS_ID` استفاده می‌شود.
- `MONITOR_BOT_TOKEN` اگر تنظیم نشود از `BACKUP_BOT_TOKEN` و بعد `TELEGRAM_BOT_TOKEN` استفاده می‌شود.
- `MONITOR_DISK_WARN_PCT=85`
- `MONITOR_BACKUP_MAX_AGE_HOURS=14`
- `MONITOR_REPEAT_ALERT_MINUTES=60`
- `MONITOR_LOCAL_BACKUP_DIR=/path/to/local/backups`
- `MONITOR_LOCAL_BACKUP_LOG=/var/log/davarna-local-backup.log`

4. Suggested cron (UTC):
- `30 1 * * *` backup
- `0 2 * * *` cleanup receipts
- `*/5 * * * *` monitoring

## 5) Baseline Hardening

- Enable swap (2G suggested for 4G RAM).
- UFW: allow only required ports (`22`, `80`, `443`, `2053`, `5678`, `1356`, `1357` + any extra x-ui inbounds you use).
- Docker logging cap: `json-file` with `max-size=10m`, `max-file=3`.
- Service restart policy: `unless-stopped`.

## 6) Smoke Test

```bash
docker compose --env-file .env.prod ps
docker compose --env-file .env.prod logs backend --tail=100
docker compose --env-file .env.prod logs bot --tail=100
curl -I http://127.0.0.1:18080/health/db
curl -I https://davarna.peymoonnet.de/health/db
```
