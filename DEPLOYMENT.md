# Davarna Deployment (Host Nginx + Docker Compose)

## 1) Production Environment Files

1. Fill `./.env.prod` (root env for backend/mysql/redis).
2. Fill `./davarna-bot/.env.prod` (bot runtime env).
3. Required keys in `.env.prod`:
- `NGINX_SERVER_NAME=davarna.peymoonnet.de`
- `BACKEND_HOST_PORT=18080`
- `BACKUP_CHAT_ID=-100xxxxxxxxxx`
- `BACKUP_BOT_TOKEN=` (optional; empty means reuse `TELEGRAM_BOT_TOKEN`)

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

3. Suggested cron (UTC):
- `30 1 * * *` backup
- `0 2 * * *` cleanup receipts

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
