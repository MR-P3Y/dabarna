# Davarna GitHub Ready Export

This folder was generated from the current live server state and cleaned for source control.

## Included

- application source code (`backend`, `davarna-bot`)
- deployment assets (`deploy`, `scripts`, `docker-compose.yml`)
- safe example env files only
- schema-only database export for reference

## Removed for Safety

- real `.env` files and secrets
- runtime storage and uploaded receipts
- virtual environments and caches
- private full database dump
- temporary backup artifacts

## Before Push

1. Confirm the target repository is private for the first push.
2. Review `.env.example`, `.env.prod.example`, `davarna-bot/.env.example`, and `davarna-bot/.env.prod.example`.
3. Do not add `E:\DAVARNA_DB_PRIVATE_20260228_012302.sql.gz` to Git.
4. Review `README.md`, `DEPLOYMENT.md`, and `PRE_PUSH_CHECKLIST.md`.

## Git Commands

Run these inside this folder:

```bash
git status
git remote add origin <YOUR_PRIVATE_GITHUB_REPO_URL>
git branch -M main
git push -u origin main
```

If `origin` already exists:

```bash
git remote set-url origin <YOUR_PRIVATE_GITHUB_REPO_URL>
git push -u origin main
```

## Deploy Reminder

This export is suitable for code hosting and controlled redeploys.
It is not a full live-server image because production secrets and runtime data were intentionally excluded.
