# Davarna GitHub Ready Export

This folder was generated from the current server state and cleaned for public publishing.

- Real env files were removed.
- Only blank example env files are included.
- Runtime data (storage/receipts), virtualenvs and backups were excluded.
- This export is intended for GitHub/private code hosting, not as a full live server image.

Before deploy:
1. Fill `.env.prod.example` into a real `.env.prod`.
2. Fill `davarna-bot/.env.example` or `davarna-bot/.env.prod.example`.
3. Review `docker-compose.yml` and deploy settings for your target server.
