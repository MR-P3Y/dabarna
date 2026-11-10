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


## 2026-11-10 historical review coverage + readiness visibility (UNRELEASED)
- Experimental old-destination monitoring now includes REJECTED invoices alongside EXPIRED and CANCELLED, without allowing automatic credit for any of them.
- Owner-only readiness diagnostics (experimental database only) include presence/time and success/failure of the latest per-destination scan observation. The report always sets `scan_coverage.backfill_verified=false`, even if a stored JSON payload misleadingly says otherwise.
- Activation remains blocked regardless of a successful recent scan; the operational scan observation is not a chain history checkpoint.
- Four isolated regression cases cover missing/tampered/incomplete observations and REJECTED coverage. The pinned isolated runner includes them.
- Tests at this new source SHA have NOT run on NODE2; no merge, no Production release, no wallet address change.
- Remaining: verified provider pagination and time-window backfill with durable checkpoints, complete historical mismatch/reconciliation workflow, safe audited activation and rollback UX in Mini App/Bot and comprehensive MySQL/network replay validation.


## 2026-11-10 operator clarification: earlier deposits were test-only (UNVERIFIED)

The operator reports no real funds moved during earlier TON/TRON trials and authorizes removal of test records if needed. This changes the proposed migration plan but is **not** database proof that all rows are disposable. Do not infer cleanup eligibility from status alone, and do not execute production DELETE/TRUNCATE, wallet ledger rewrites or balance reset without a separate evidence-based scope.

A read-only SQL dependency audit is available at `dev/release/audit-crypto-test-history-readonly-20261110.sql`. It counts invoices by network/status, tx hashes, chain detections, credit links, crypto wallet ledger entries, orphaned ledger entries and nonzero wallet balances. Run on NODE2 with a read-only SQL account and preserve the output without exporting private user data. Compare against a verified snapshot/backup and classify exact test invoice IDs.

If there are **no** crypto invoice rows, no crypto ledger entries, and no linked transfer evidence, the old-invoice historical-reconciliation release blocker for this specific database can be eliminated **without deleting anything**. Do not generalize this to other databases or networks. If any linked credit/ledger/chain evidence exists, preserve accounting history and escalate those rows for explicit reconciliation, even if the initial scenario was a test.

The ability to switch active wallet destinations in Production remains blocked independently by provider preflight, atomic live state/bootstrap, authenticated UI/Bot activation, rollback and end-to-end chain-to-ledger regression coverage. The existing disposable-only rotation guard must not be relaxed merely because old invoices are test data. This documentation is planning only; no Production data mutation has occurred.


## 2026-11-10 release-track correction: destination switching only
- Project focus restored: deliver owner-controlled TON/TRON destination rotation. **No wallet balance reset, ledger deletion or Production cleanup is part of this PR's release path.** The finance audit found one 100,000-toman ledger discrepancy, tracked separately and not changed here.
- Fixed a successive-rotation bug: proposal/readiness previously compared against the static environment address even after the disposable versioned address had changed. Experimental mode now compares with `CryptoDepositService.runtime_status(db)` (persisted versioned destination), while Production proposal behavior still reads its configured environment address.
- Experimental owner-only proposal listing now includes the actual persisted destination and version for guarded compare-and-swap activation; the nonexperimental response never exposes an activation version or enables the action.
- Mini App now renders an additional double-confirmed **disposable-test-only** activation control only when server explicitly advertises `activation_supported=true`. The endpoint remains hard-gated to `davarna-wallet-mysql/davarna_wallet_rotation_test`; production activation is not implemented or implied.
- Five new HTTP regression cases in `test_mini_crypto_address_proposals.py` cover second rotation, versioned readiness, production isolation and test-only activation metadata.
- Pending: execute pinned isolated suite and disposable MySQL suite for this HEAD, verify Mini App JS syntax, add a separate production-safe startup/bootstrap and rollback policy, implement Bot approval UX, provider preflight and transaction replay checks, and release only with a dedicated explicit deployment approval.


## 2026-11-10: production wallet rotation implementation candidate (UNTESTED)
A *new, default-off* gated Production mode is implemented in this branch. It is **not activated or deployed** merely by merging the code.

### Security and concurrency
- `DAVARNA_CRYPTO_ROTATION_PRODUCTION=I_ACK_REAL_FUNDS_PRODUCTION_WALLET_ROTATION` and `DAVARNA_CRYPTO_ROTATION_PRODUCTION_DB=<verified exact schema>` must BOTH be explicitly set in the backend process, and actual `DATABASE_URL` must be MySQL with `mysql` hostname and matching database. Otherwise production mode remains OFF.
- The separate experimental endpoint accepts only exact disposable MySQL and is not unlocked by the production gate.
- Issuance, crypto runtime toggling (both Mini and Bot endpoints), and destination rotation coordinate with SQL row locks. Runtime is locked BEFORE versioned destination to avoid opposite lock ordering.
- Owner-only initial bootstrap `POST /mini-api/admin/super/crypto-address-prepare-production` seeds a version 1 state from the existing configured env address, only while a **persisted runtime setting exists and is FALSE**. It does not change recipient addresses, and repeated initialization is refused.
- Owner-only `POST /mini-api/admin/super/crypto-address-activate-production` requires a pending proposal, matching active version/address, the prior-address SHA256, disabled issuance, zero open/recent-closed/needs-review/**any historical** invoices on that address, and a successful read-only query of the proposed destination via TronGrid or TON provider. All writes and audit commit atomically.
- Production activation **never reenables user deposits**. The operator must separately verify live status and explicitly resume them.
- Pending destinations display actual database versions only after bootstrap; without bootstrap, the owner can see preparation state while issuance remains frozen, but invoice creation fails closed.
- Bot owner crypto menu includes read-only address overview, backed by the existing protected `/bot/admin/crypto-settings` route. Direct Bot approval was deliberately NOT added: a shared Bot admin token is insufficient identity for destination mutation; approval must use authenticated Mini App ownership.
- Owner-only `GET /mini-api/admin/super/crypto-late-review-production` surfaces unmatched historical transfers for manual review without any credit action.
- Regression tests added for runtime off, exact production database gate, stale version, unresolved history, failed provider preflight, successful audited CAS handler and non-enabling of deposits. Both test harness and bot-source compile checks are included in pinned isolated runner.

### Current deployment blockers — IMPORTANT
- **The live DB currently contains 20 closed historical crypto test invoices (14 TRON, 6 TON) on the old environment destinations.** They are NOT automatically deleted or hidden. The new production activation endpoint intentionally denies any switch while a historical invoice references the previous address. This must be resolved through a separate, auditable reconciliation decision; never reset wallets or delete the game ledger.
- The current historical scanner only scans a bounded recent lookback for older invoices. It does not certify historical backfill. The read-only late review queue does not authorize auto-credit.
- **No Production runtime gate has been enabled**, no Production address has been changed, and these latest candidate commits **have not been tested yet**. Older commit `3ca9d6a7...` passed 66 isolated + 9 disposable MySQL tests; do NOT count those as validating the new production code.
- Do NOT set the Production opt-in environment variables, merge as ready-to-use, or deploy with live funds until the newly pinned release-candidate suites pass, proper historical invoice treatment/backfill is tested, external chain/provider preflight is checked, and a reversible deployment checklist is approved.

### One-shot isolated validation
Pin the latest branch head in `DAVARNA_WALLET_RELEASE_TEST_REF`; execute `dev/release/verify-wallet-rotation-release-candidate-20261110.sh` only with `DAVARNA_WALLET_RELEASE_TEST_APPROVAL=RUN_ISOLATED_WALLET_RELEASE_TESTS`. All MySQL tests run in disposable container `davarna-wallet-mysql` on isolated network with tmpfs; the script never deploys to Production.
