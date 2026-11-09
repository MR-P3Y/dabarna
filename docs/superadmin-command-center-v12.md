# Superadmin Command Center V1.2 — release gates

Branch: feature/superadmin-command-center-v12-20261110
Parent: V1.1 RBAC merged into feature/superadmin-live-dashboard-v11-20261109.

## Implemented
- Actionable monitoring KPI cards: game queue, bank deposits, withdrawal queue, crypto review and risk alerts.
- Inspectable service-status cards without implying independently verified health.
- Direct navigation within the Superadmin workspace for wallet settings, bank cards and role management.
- Address-change **proposal only** for TRON/USDT and TON. Superadmin/owner restriction, explicit confirmation, checksum/format validation, auditable AppSetting record, duplicate/stale request rejection.
- Explicitly no switching of active invoice destinations, block scanners, env variables, or payment settings.

## Critical missing scope before active wallet change
The existing CryptoDepositService.configured_options() uses config environment addresses; CryptoChainService TRON/TON scanning also uses fixed environment addresses. Switching only the displayed address would strand deposits.

To enable true in-app active wallet edits, first implement and test:
1. Multi-address scanning of active and retired invoice destinations, for every open/pending/grace-period invoice.
2. Atomic versioned active destination selection with compare-and-swap; persist per-invoice destination snapshot.
3. Scanner preflight to verify the new address on the correct network and provider health; do not silently accept a bad address.
4. Freeze or prevent concurrent new invoice issuance during the change transaction; deterministic old/new invoice mapping.
5. Block unsafe activation while unsettled invoices cannot be scanned, detect duplicate transfers and preserve idempotent credits.
6. Two-step activation with owner-only authorization, separate approval, audit event and rollback; disable activation unless all isolated regression tests pass.
7. Isolated MySQL chain mocks covering both networks, transfers before/during/after switch, retries and restart; never use Production for tests.

## Test commands (disposable only)
- Node: node backend/tests/js/test_superadmin_dashboard_v11.mjs
- Python (backend dependencies): python -m unittest backend.tests.test_mini_crypto_address_proposals -v

## Release restriction
Do NOT merge/deploy to Production until tests above pass and the user explicitly approves wallet-related Production deployment. A staged proposal is not an active destination change.
