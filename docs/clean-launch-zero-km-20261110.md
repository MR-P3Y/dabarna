# Davarna clean launch — zero-kilometer cutover

Status: **PREPARATION ONLY.** This document does not authorize deletion of the old
Production volume, user data, logs, invoices, backup or ongoing deposits.

## Approved product intent
- Start the next production season without migrating historic game, finance,
  crypto invoice or wallet balance data.
- Finish owner-controlled TON + TRON USDT destination management in V1.2.
- Preserve production credentials, owner identity, staff roles/configuration as
  *separately authorized new configuration* — never copy old financial DB.
- Archive the old instance and its data before any cutover; retain a rollback
  option until the first new paid transaction is reconciled.

## Important architecture facts
- Root `docker-compose.yml` pins names (`davarna-mysql`, `davarna-backend`,
  `davarna-redis`, `davarna-bot`) and named volumes. It **cannot** safely
  be reused as an independent preview merely by changing the Compose project.
- Backend Dockerfile runs `alembic upgrade head` and
  `python -m app.scripts.seed_initial` at startup.
- Frontend build only outputs WalletConnect bundles. They must not overwrite
  the `app/static/mini/*.js` changes in the same release.
- Startup seed inserts default `roles` and `app_settings`, but does not
  create a new owner user or grant owner role. Separately verify Telegram
  owner identity / RBAC, not by importing old wallet records.
- A blank DB does not imply all payment switches are safe: both
  `CRYPTO_PAYMENTS_ENABLED=false` in container environment and persisted
  `crypto_payments_runtime_enabled=false` must be verified before cutover.
- Neither the Bot nor the autopilot should start in a second parallel
  production-like stack with the existing Telegram credentials.

## Gates to move forward (must all PASS)
1. Freeze issuance/game settlement/wallet writes on OLD instance only
   **after an announced maintenance window**, check no unresolved real-fund
   deposits/withdrawals, and capture final database+file+config snapshots.
   Earlier archive exists but is **not** the cutover final backup.
2. Independently verify backup recoverability and integrity; do not copy
   old wallet balances, invoices, purchases or game transactions.
3. On an isolated network with disposable MySQL, execute
   `dev/release/test-clean-launch-fresh-db-20261110.sh`: full migrations,
   initial role/config seed, and verify zero users, wallets, wallet_txs,
   games, purchases, crypto invoices, deposits and withdrawals.
4. Run `dev/release/verify-wallet-rotation-release-candidate-20261110.sh`
   for the **same exact immutable Git SHA** and verify 1) JS and Bot syntax,
   2) HTTP/RBAC/payment safety, 3) disposable MySQL concurrency.
5. Prepare *new* production stack and volume paths separately from old
   ones, with unique container names, unique Redis data, isolated network,
   TLS/proxy planning, secrets and backups; do not reuse the original
   Compose labels or old DB volume for staging.
6. On fresh DB, configure only new, validated receiver addresses and exact
   owner identity. Set deposit runtime OFF. Bootstrap TON/TRON destination
   version 1 explicitly with authenticated owner UI.
7. Confirm current owner status, new destination addresses, provider
   preflight, user account onboarding, daily limits, manual deposit flow,
   payment reconciliation, game/call/winner/idempotency; use test funds and
   verify rollback before accepting public deposits.
8. Explicit production cutover approval includes immutable commit SHA,
   new clean DB name, server instance, planned service interruption,
   preserved old backup/volume, payment ON/OFF choice, and rollback owner.
9. After cutover, monitor health and transaction-to-wallet reconciliation.
   Old stack/volume must be **retained but inactive** until a separate,
   specific, post-cutover deletion approval.

## No destructive short-cuts
- No `DROP DATABASE`, `TRUNCATE`, `docker compose down -v`,
  `docker volume prune`, `UPDATE wallets SET balance=0`, nor
  deleting `wallet_txs` in an active production database.
- A "fresh launch" is **new empty schema + newly initialized instance**,
  not mutating financial ledger records of the existing instance.
- The old historical 20 invoices do not block new empty DB setup, but the
  old environment must still honor its own unresolved-funds obligations
  if that instance is ever resumed.

## Current phase
Only source preparation, test harnesses and documentation have been
committed. The latest candidate MUST be tested on NODE2 before deployment.
