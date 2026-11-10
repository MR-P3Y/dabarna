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

## 2026-11-10 rotation preflight stage (draft, not deployed)

- TronGrid mocked contract: requests for old and new destination separately, filters unrelated recipient and verifies confirmed transfer.
- TON Center mocked contract: account parameter, network destination and memo for old/new addresses.
- Provider outage is fail-closed; never interpret HTTP 503 as an empty successful scan.
- Read-only `GET /mini-api/admin/super/crypto-address-readiness?network=TRON|TON` (owner-only) reports open invoices, recently expired/cancelled invoices within grace, manual review count. UI provides a "بررسی آمادگی تغییر آدرس" action.
- Expired or cancelled invoices are **not auto-credited** by this stage. Late/unmatched transfers require an explicit audited reconciliation/manual-review workflow.
- `active_change_allowed` is always false. This is a deliberate hard gate, not a bug.

### Remaining requirements for atomic activation
1. Seed and lock a persistent destination-version row during **every** invoice issuance and activation transaction; without a shared DB lock, activation can race invoice creation.
2. Use the versioned destination for option rendering, invoice creation, preflight and worker scans; preserve immutable destination per invoice. Keep scanning retired destinations through their outstanding/grace windows.
3. Reconciliation must include historical destination addresses as well as current address, and surface unmatched late transfers without automatically crediting expired invoices.
4. Provider scans must handle pagination and lookback gaps, independently verify new destination before activation, and fail closed on any degraded network.
5. Explicit owner confirmation, separate operator authorization where required, immutable audit record and rollback transaction; never enable with unresolved review cases.
6. Run realistic isolated MySQL payment/idempotency tests, concurrency tests, and restart/rollback tests prior to any production finance rollout.

## 2026-11-10 experimental atomic revision prototype (UNRELEASED)

- Introduced `crypto_destination_state.py` with strict experimental gate. It only enables against `mysql+pymysql://...@davarna-wallet-mysql/davarna_wallet_rotation_test` *and* `DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL=I_ACK_DISPOSABLE_DB_ONLY`.
- A destination version row must **already exist**. A missing row is not lockable; the code fails closed (503), rather than racing to create it during invoice issuance.
- When the gate is on, invoice creation reads its destination via a `SELECT ... FOR UPDATE` lock held until the caller commits the invoice. Rotation must lock the same row and compare the previous version/address; a revert increments the version, not rewrites history.
- Proposed rotation methods **do not expose an activation HTTP endpoint**, do not call commit themselves and do not change Production defaults.
- Serial unit tests added, plus opt-in disposable MySQL concurrent writer/reader locking tests. These are not yet executed on NODE2. SQLite alone cannot validate row-lock concurrency.

### Mandatory unfinished work before activation

- Prove MySQL lock behavior with the dedicated disposable database and concurrent invoice creation + rotation; review transaction isolation and deadlock retries.
- Version-lock all options/preview paths with their stated consistency semantics; any address shown to users must correspond to invoice destination at issuance.
- Implement rollback-safe, audited activation endpoint and action UI only behind separate explicit Production authorization and comprehensive tests.
- Create durable historical-address scan coverage after expiration/cancellation and handle provider pagination and unmatched late transactions.
- Add adversarial idempotency, restart, retry, finance-ledger and failure-injection suites.

## 2026-11-10: MySQL invoice snapshot + replay safety tests (draft)

- Add a third **real disposable MySQL** regression: concurrently insert an invoice destination snapshot while a rotation waits for the exact row lock; verify persisted snapshots are `OLD/v1` then `NEW/v2`, and rollback to `OLD/v3` does not mutate either old invoice.
- Add four no-network replay/expiry checks: previously credited/rejected transfer hash never recredits, expired invoice is not auto-matched, and mismatched idempotency replay is rejected.
- These are tests, **not** implementation of real invoice issuance or historical-address reconciliation; the snapshot table is deliberately dedicated and disposable.
- For late payments currently excluded from OPEN_STATUSES, manual-reconciliation indexing and audit workflow remain unimplemented; do not claim expired payments are safely reconciled.
- No Production deploy / no active address activation. New tests await NODE2 execution.

## 2026-11-10 actual invoice and ledger regressions (untested on NODE2)

- Disposable MySQL suite now includes a `CryptoDepositService.create_invoice` integration test with real `User`, `CryptoDepositRequest`, and versioned `AppSetting` models. It creates an invoice while a rotation transaction holds the row lock, then confirms the invoice snapshots the committed new address. Returning the active address to the old one doesn't rewrite the earlier invoice, and a second user's invoice uses the returned address.
- A separate MySQL integration test creates a real `Wallet` and `WalletTx`, credits with `WalletService.credit`, then retries in a fresh Session as a worker restart simulation; verifies one ledger transaction and unchanged balance.
- Only the quote/preflight and service enablement are mocked; no chain provider calls and no external transfers.
- These checks do **not** implement automatic late-payment reconciliation or activation endpoint. Actual `process_transfer` end-to-end replay and scanner retry orchestration still require separate tests; avoid treating a green result as permission to deploy financial changes.


## 2026-11-10 pagination guard (not released)

- TRON/USDT scans now follow TronGrid `meta.fingerprint` while preserving request filters, both for pending and confirmed transfer views. Repeated cursors, malformed response data, an unpaginated full page and more than 20 pages fail closed.
- TON scans now follow TON Center v3 `offset` in increments of 100; malformed pages, HTTP errors or more than 20 pages fail closed. No truncated page result is handed to the crediting worker.
- Four new mocked pagination tests are included in the V1.2 isolated test runner alongside late-transfer inbox tests.
- Commits: `9d92ced8ce64e2c38780af55e41b30fea2a9987d`, `19966a4fb1a3e8bc5af344a5e93b66ec274962f8`, `92d3280f9606e492e6f95e9a30a3a13d40084b2f`.
- **Not run on NODE2 yet.** Fail-closed scan overflow requires operational alerting and persisted backfill/cursor support; no automatic credit should occur from incomplete history.
- Full production capability **still blocked** on final historical late-payment reconciliation, end-to-end chain event/ledger tests, provider health preflight, auditable user-controlled activation and rollback, and explicit separate finance release approval. Do not flip experimental gate or merge as a ready-to-deploy wallet rotation.


## 2026-11-10 staged TON attribution hardening (NOT DEPLOYED)
- Experimental, disposable-MySQL-only address rotation refuses to infer TON invoice ownership by payment amount alone when the TON memo is missing or mismatched.
- Claimed transaction-hash invoices require their nonempty invoice memo to match the actual chain memo.
- This stricter attribution applies **only** when `rotation_enabled()` is true; default Production matching behavior remains unchanged.
- Five isolated regressions cover missing, wrong, exact and legacy memo handling. Included in the V1.2 pinned test harness. New tests have NOT been run on NODE2.
- Activation remains disabled for Production. Changing only an address shown in UI is NOT a safe migration. Current experimental endpoint additionally blocks any historical invoice at an old address; this is not a completed historical reconciliation solution.
- Remaining to implement and test: authenticated owner-operated activation/rollback UI and Bot flow, scanned and persisted old-address history/backfill and missed-page recovery, immutable audit trail, real-chain provider preflight, late-transfer manual resolution policy and noncredit review actions, unified isolated MySQL end-to-end chain-to-wallet settlement, restart and failure injection.


## 2026-11-10 historical scan-gap alarm (UNRELEASED)
- Crypto worker now explicitly emits `CRYPTO_HISTORICAL_SCAN_GAP` at ERROR level if the earliest historical/open invoice for a scanned address predates the configured lookback floor while experimental rotation is enabled.
- Per-cycle `historical_gaps` counter reports the number of detected incomplete address scans; the current recent scan still proceeds, preserving existing invoice service. Address appears as a short SHA-256 hash, not a plaintext secret.
- Four isolated regression tests cover old invoice alarm, recent overlap, empty history and legacy (rotation-off) compatibility; wired into the pinned V1.2 test harness.
- **This is detection, not historical backfill.** The worker still cannot guarantee completeness when provider pagination bounds are exhausted or older transfer history is missing. The experimental activation endpoint still blocks historical invoices at the old destination.
- To safely activate real address rotation, first implement a durable per-address historical scan checkpoint/backfill with explicit provider coverage verification, monitor unresolved gaps and manual review queue, and complete MySQL end-to-end payment/ledger tests.
- New code remains untested on NODE2, PR remains Draft, and Production activation is prohibited.


## 2026-11-10 experimental durable scan observations (UNTESTED, UNRELEASED)
- A new `crypto_scan_observation_v1:` per-(network,address) AppSetting stores the latest attempted scan floor, per-attempt page completion, transfer-processing completion, detected historical gap and count. Address is represented by a SHA-256 digest; no plaintext destination is stored in the observation.
- A network provider failure records an incomplete attempt; processing errors mark the scan incomplete. A problem scanning one destination must not stop scanning another.
- Observations are only written when disposable-MySQL rotation mode is active. Existing production behavior remains unchanged.
- `backfill_verified` is deliberately **always false**. Recent page completion is not evidence that all historical transfers were scanned or that a payment has been reconciled. The observation row is operational diagnostics, not a cursor suitable for historical catch-up.
- Four isolated tests added to the V1.2 harness. They have not been run on NODE2 at this new head.
- Remaining prerequisite: persisted historical paging checkpoints with verifiable coverage/repair, a trusted manual late-payment resolution workflow, and full integrated chain-to-ledger tests. Do not activate or deploy this wallet-rotation branch to Production.
