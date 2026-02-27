# Davarna

GitHub-ready export of the current Davarna production codebase.

This export was taken from the live server and cleaned for source control.

## Included

- `backend/` FastAPI backend
- `davarna-bot/` Telegram bot
- `deploy/` Nginx/Certbot deployment assets
- `scripts/` operational scripts
- `database/schema_only.sql` database schema backup
- `.env.example` and `.env.prod.example` safe example env files

## Not Included

- real `.env` secrets
- runtime storage and uploaded receipts
- Python virtual environments
- private full database dump

## Private Backup

The full private database dump is stored separately and must not be pushed to public GitHub:

- `E:\DAVARNA_DB_PRIVATE_20260228_012302.sql.gz`

## Publish Flow

1. Review `.env.prod.example` and create a real `.env.prod` for your target server.
2. Review `davarna-bot/.env.example` or `davarna-bot/.env.prod.example`.
3. Review `docker-compose.yml`.
4. Push this folder to a private repository first.

## Compose Notes

- `docker-compose.yml` is production-oriented.
- `backend` expects env from `BACKEND_ENV_FILE`.
- `bot` expects env from `BOT_ENV_FILE`.
- `nginx` is behind the `edge` profile.
- local bind for backend is restricted to `127.0.0.1`.

## Database Notes

- `database/schema_only.sql` is safe for source control.
- Full data backup is intentionally not inside this repository export.
