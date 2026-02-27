# Pre-Push Checklist

Use this checklist before pushing the Davarna export to GitHub.

## Repository Safety

- [ ] The destination repository is private for the first push.
- [ ] `E:\DAVARNA_DB_PRIVATE_20260228_012302.sql.gz` is not inside the repository.
- [ ] No real `.env` or `.env.prod` files were copied into this folder.
- [ ] No receipt images, runtime storage, logs, or backups are present.

## Files to Review

- [ ] `README.md`
- [ ] `DEPLOYMENT.md`
- [ ] `PUBLISHING_NOTES.md`
- [ ] `docker-compose.yml`
- [ ] `.env.example`
- [ ] `.env.prod.example`
- [ ] `davarna-bot/.env.example`
- [ ] `davarna-bot/.env.prod.example`

## Technical Checks

- [ ] `git status` is clean or contains only intended changes.
- [ ] The branch is `main`.
- [ ] No hard-coded token, password, API key, chat id, or private URL remains in tracked files.
- [ ] `database/schema_only.sql` is schema-only and contains no live business data.

## Recommended First Push Flow

```bash
git status
git remote add origin <YOUR_PRIVATE_GITHUB_REPO_URL>
git branch -M main
git push -u origin main
```

## After First Push

- [ ] Re-check GitHub web UI for accidental secrets.
- [ ] Add collaborators only after the repository is verified clean.
- [ ] Keep the full database dump offline or in a private backup location only.
