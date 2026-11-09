# Davarna v1.0 — release candidate and freeze

**Candidate branch:** `release/davarna-v1-candidate-20261109`
**Baseline:** `release/combined-forum-mini-candidate-20261107`
**Combined changes:** #33 (stored game rule / Telegram routing), #34 (per-target lifecycle delivery ACK and restart retry). Does **not** include #32 crypto destination draft changes.

## v1.0 scope
- Existing Bot and Mini App operations, including wallet, purchases and winner settlement, are **unchanged by this release candidate**.
- Card rules: LINE (LOW/MEDIUM) 3×9 / 15 numbers; Tourna 3 of any single row, Line 5 of any single row. FULL_CARD (HIGH) 15 numbers / no Tourna. LEGACY remains original 4×5 / 20 numbers.
- Runtime: minimum 2 distinct players to start, validated by GameService and autopilot worker.
- GAME_CREATED/STARTED/ENDED user/admin notifications now use stored rules, optional start topic (unset by default), and persistent per-destination ACKs with retry on unsuccessful Telegram sends. Existing announce/live/result topic routing remains unchanged unless opt-in start topic is explicitly configured.
- No game price, commission, wallet, payout, crypto settings, migration, or autopilot runtime flag is changed as part of this candidate.

## Evidence and final offline gate
- PR #33 isolated forum contract: 6/6 PASS on NODE2.
- PR #34 isolated ACK/restart and forum regression: 21/21 PASS on NODE2.
- One combined *offline* gate script at `dev/release/test-davarna-v1-rc-offline-20261109.sh`. It runs V2 card rules, lifecycle ACK/restart, forum rule contracts, Mini API rule labels (in local read-only, offline backend image), Python syntax, and JavaScript syntax when Node.js is available.
- **Current candidate gate not yet executed.** Do not label v1.0 as deployed or fully validated on the basis of earlier independent runs.
- No CI checks found on #33/#34 SHAs; manual tests are not CI.

## Explicitly not included (v1.1 or separate approval)
- Dedicated Telegram start topic ID and real five-minute scheduled advance notice (#27) remain unverified/unimplemented; current general announce topic stays as fallback.
- Full multi-device visual redesign: superadmin dashboard (#22), game announcement card (#23), Mini notification inbox (#24), winner popup (#28).
- Actual editable live TRON/TON deposit address activation (#30); review-only draft work in #32 is **excluded** because it is financially sensitive.
- Repository and NODE2 cleanup (#26) only **after** a safe release and backed-up inventory.
- Full mobile browser, real Telegram delivery and all-financial end-to-end tests have not been rerun for this combined candidate. The user declined a separate staging environment. This acceptance limit must remain visible rather than being described as PASS.

## Release safety decision
1. Only the offline gate may run without release authorization; it never touches Production DB, crypto config, Autopilot runtime, Telegram messages, or Docker services.
2. Read-only Production preflight checks (existing health, database revision, current image/backup state and active game IDs) may be collected but do not authorize deployment.
3. Require an **independent explicit approval for merging and Production deployment**, plus a verifiable backup and rollback route. No accidental release of #32.
4. Telegram ACK retry gives at-least-once attempts, not exactly-once. A crash between Telegram acceptance and local ACK may duplicate a notice. Monitor for repeated messages.

**Freeze:** No new feature creep in v1.0. If the combined gate fails, fix only the blocking defect and rerun the same gate.
