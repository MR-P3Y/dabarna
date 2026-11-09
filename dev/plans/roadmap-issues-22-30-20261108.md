# DAVARNA: parallel work streams after finance PR #31

Date: 2026-11-08. Source: merged PR #31 (`22ddf0f`). Work branch: `feature/roadmap-crypto-rules-ui-20261108`.

## Work status and release boundaries

| Stage | Issues | Current action | Merge/deploy gates |
|---|---|---|---|
| 1 — crypto address rotation | #30 | source audit + independent strict TRON/TON validator and tests **added**; design remains incomplete | no production address changes; migration, full scanner coverage, RBAC, confirmation flow, regression tests and explicit approval required |
| 2 — game rules and Telegram messages | #25 #27 #29 | audit inventory and message routing acceptance requirements established | preserve existing topic IDs, dedupe event markers; no unsolicited Telegram group posts |
| 3 — Mini App UX | #22 #23 #24 #28 | four UI tracks scoped and ordered behind game-rule contracts | separate visual QA, accessibility checks, no wallet/Autopilot changes |
| 4 — cleanup | #26 | retention/inventory contract written | **last only**; no automatic delete |

## #30: source-backed blocking discovery

Existing `CryptoDepositService.configured_options()` returns addresses from environment variables `CRYPTO_TRON_USDT_ADDRESS` / `CRYPTO_TON_ADDRESS`. `CryptoDepositService.create_invoice()` persists the chosen address into **each invoice** as `CryptoDepositRequest.destination_address` — correct historical behavior. However `crypto_chain_service.py` obtains transfer histories and filters recipient addresses using **current config environment addresses** (TRON and TON). Therefore only changing the address selection for new invoices would leave old pending invoices unobserved by the scanner. **Do not activate the address-switching UI until that is resolved.**

### Required data and API architecture (to implement in an isolated PR)

1. DB migration introduces versioned `crypto_destination_versions` with `network`, `asset`, `address`, `version`, `state` (DRAFT/ACTIVE/RETIRED), actor, reason, timestamps and unique version/activation constraints; audit links to operation IDs.
2. REST endpoints: super-admin read-only status, `prepare` (validate canonical network and checksum, inspect open invoices, scanner readiness, return short-lived challenge and exact old/new address + version), `apply` (re-auth and challenge, compare-and-swap, idempotency key, transaction audit), `cancel`; never accept address edits in the existing runtime-toggle endpoint.
3. Client displays explicit destination/network confirmation and an irreversible-address warning; Bot and Mini App MUST call the same Backend service with role enforcement. Do not put super-admin credentials in frontend bundles.
4. Scanner must monitor a unique **set**: active address, and all addresses associated with potentially creditable invoices, including late-payment and review windows. Distinguish canonical TON raw/friendly variants, and TRON exact checksum; dedupe on `(network,tx_hash)` across all addresses. A scanner outage must block an apply rather than discard pending checks.
5. Keep `invoice.destination_address` immutable; cancel/reject/credit and ledger idempotency remain unchanged. No changes to `.env.prod` in UI. Legacy env addresses remain safe fallback until the migration and worker changes pass.
6. Security gates: actor `SUPER_ADMIN` or owner only, auth expiry, replay, double-confirmation, concurrency and stale version, secret redaction, encrypted or restricted audit as applicable, zero balance changes. Run dry-run and restore rotation on isolated MySQL with synthetic invoices.
7. Independent deployment authorization for **code/migration** and separately for **real address rotation**. Neither is granted by the request to start development.

Initial validator: `backend/app/services/crypto_address_rotation_validation.py`. This is **not wired to Production**, and does not assert that an address belongs to the operator or that the target wallet can receive funds.

## #25 / #27 / #29: audit order and acceptance

1. Build a matrix of `game_rule` × surfaces: backend game creation and outcome, bot help/active game/cards/winners, Mini App list/cards/purchase/notifications, Telegram announce/live/results/admin topic. Mark each PASS/FIX/NOT_TESTED after reading actual render/serializer source and running a contract test.
2. Validate LOW/MEDIUM = LINE, v2, 3×9 board, 15 values; Torna = 3 numbers in one row; LINE = 5 numbers in one row. HIGH = FULL_CARD, 15 values, no Torna. LEGACY = 4×5, 20 values. Use persisted `game_rule`, never topic labels to decide rule. Two **distinct** players minimum, game-specific pool/commission, no fixed prize assumptions.
3. Current `davarna-bot/bot/services/user_topics.py` maps `announce` to `USER_TOPIC_ANNOUNCE_ID`; there is no separate configured game-start announcement topic. `notifier.py` announces game created/started to `announce`. The real new topic ID must be verified before rerouting. Avoid asserting a five-minute pre-start notice for player-triggered starts until an actual clock schedule exists.
4. Extract actual Telegram HTML message templates from `davarna-bot/bot/workers/notifier.py`, `backend/app/routers/mini_router.py`, and bot help. Test escaping, length, missing data, links, routing, and restart-safe event dedupe.
5. Only after the audit, implement route and message changes on a **separate Bot PR**. Keep live routes unchanged until verified and approved.

## #22 / #23 / #24 / #28: UI implementation order

- #22: common mobile RTL design tokens, dashboard section hierarchy, live-last-updated timestamps tied to real fetches, protected actions and loading/error/empty states.
- #24: notification Inbox categories and read states using existing `/mini-api/me/notifications`, with no fake realtime and no duplicate polling.
- #23: announcement/game card real `game_rule`, status and link; timer only when API gives an authoritative start; do not expose account information.
- #28: winner modal with award-kind labels derived from persisted rule, multiwinner support, one-time event display without touching payouts.
- Shared checks: desktop/mobile and Telegram WebView, light/dark, keyboard focus/Escape, `prefers-reduced-motion`, text escaping, role authorization. Visual preview before independent publish.

## #26: last-stage cleanup inventory

Inventory first: GitHub branches/PRs/releases; disk and RAM/swap; Docker images/volumes; artifacts; test containers; backup/receipt/env/secret directories. Explicit per-item deletion consent; **never** delete Production financial backups, receipts, wallets, database volumes, rollback images, or credentials during inventory. Keep separate cleanup and rollback plan with final health smoke tests.

## Non-goals of this initialization

No production crypto configuration changes, no wallet or ledger writes, no new group announcements, no bot restart, no deletion, and no automatic feature rollout.
