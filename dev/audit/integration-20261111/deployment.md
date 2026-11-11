# Approved Production deployment — 2026-11-11

The owner separately approved merging PR #50 and then approved Production deployment. PR #50 was merged into `release/davarna-v1-candidate-20261109` as `98fcce1dd2e127366367b378d47150530bb9b850`. The merged tree matches the reviewed PR head. This receipt supersedes the earlier **not merged / not deployed** status in `report.md`; the earlier test results remain the pre-release evidence.

## Exact release

The already-built and tested images from runtime source `850a6db` were exported, transferred, checksum-verified and loaded without rebuilding. Later source commits only add tests and audit artifacts.

| Service | Deployed image | Image ID |
|---|---|---|
| Backend | `dabarna-backend:rc-850a6db` | `sha256:e713ff8b7a43a800549b94048efba403ee6e7314a28ae72a1cd7a73e33cf7731` |
| Bot | `dabarna-bot:rc-850a6db` | `sha256:9f2bad21e0f3884a7f31151accb3a06c5229991194afdc5685af22751fa1d47b` |

Backend started at **2026-11-11 14:43:54 UTC / 18:13:54 Asia/Tehran**; Bot started at **14:44:01 UTC / 18:14:01 Asia/Tehran**.

## Deployment verification

- Exact prior runtime image IDs were checked before mutation; both services were healthy.
- Each service used its own actual Compose chain. Effective Compose configuration was compared before/after, allowing only image, explicit environment preservation and startup command changes.
- Every runtime environment value and every storage mount was checked for equality before/after deployment. Secrets were stored only in root-restricted server backups, not in this report or Git.
- Backend starts directly with `uvicorn app.main:app --host 0.0.0.0 --port 8000`. The Dockerfile's migration/seed wrapper was bypassed.
- Schema stayed at `20261108_0012`; Autopilot per-level settings were equal before/after. Existing worker flags were preserved.
- Bot was stopped while Backend was replaced. Persistent notification state was backed up after stopping; Bot restarted using the same storage.
- Both new containers became healthy; MySQL and Redis stayed healthy. No database service recreation, migration, seed, manual financial operation or deliberate game mutation was performed.
- Samples at 14:44:23 and 14:46:05 UTC: all four services healthy, zero container restarts; `/health/db` returned HTTP 200 and `ok=true`; `/mini/` and `/mini/app.js` returned 200; served JS contained V1.3 and scheduled-start countdown code; unauthenticated `/mini-api/admin/ops-dashboard` returned 401.
- Runtime log inspection at 14:45:23 UTC: zero ERROR/CRITICAL lines and zero tracebacks in either new application container. The ACK file parsed successfully and all prior event markers were retained or advanced.
- Worker startup messages were not present in the sampled logs. Preserved flags and healthy startup do **not** by themselves establish a newly observed full live game cycle.

No test messages were sent to real Telegram users. Normal application workers resumed their configured operation. Synthetic purchase, payout, notification and concurrency checks remain isolated-test evidence, not newly executed live financial tests.

## Additional image-level test

Ran 24 purchase-entrypoint, lifecycle ACK and countdown-notice tests inside the exact deployed Bot image with `--network none` and a dummy token: **24 passed**.

The first run used an incorrect test mount (`/tests`); one source-path check failed looking for `/bot/workers/notifier.py`. Corrected the mount to `/app/tests`. A subsequent passing run exposed a missing level-topic sender mock in the AST-based lifecycle test: the production function exists, but its test namespace omitted it and the notifier correctly caught the resulting exception. Added the missing mock and assertions that its ACK persists and prevents a second send. The final 24-test run passed without that exception. No assertion was removed or disabled; runtime code and deployed images were unchanged.

## Rollback prepared, not exercised

The server's root-restricted deployment directory contains before/after container inspections, normalized Compose snapshots, schema/settings snapshots, Bot ACK backup, per-service upgrade/rollback overlays and deployment logs. Do not copy these raw files into Git: they contain runtime environment values.

Prepared previous images:

- Backend `davarna-backend:superadmin-v13-247c2be`, ID `sha256:4bfe2afa070fa9ca330f70e02ce2233bf2dcf33fb7aa21a1335fc3666cce04e3`.
- Bot `davarna-bot:v1-notices-9cb6876`, ID `sha256:2b22618bc4fd5fb2f6e430c501acaf11716c91bce158277895f18f38ba038b7a`.

The deployment runner had automatic rollback on failed startup or post-deployment invariant checks; that branch was not triggered and is not claimed Production-tested. For a future separately authorized rollback: verify no subsequent release drift, stop Bot, recreate Backend from its exact saved Compose chain plus backend rollback overlay using `--no-deps --no-build --pull never`, verify health, then recreate Bot from its own chain plus bot rollback overlay and verify health/HTTP/ACK. Preserve the current data volumes and current ACK file; do not restore old financial data, downgrade schema, run seed, or rewind ACK markers. Backend rollback also uses direct Uvicorn startup.

## PR disposition refresh

GitHub API refresh after deployment found the same 18 older open PRs, with no additional unaudited PR. PR #50 is merged and deployed. The follow-up PR containing this receipt and the stronger lifecycle test has no runtime changes and needs no deployment.

- Ready for review/merge: the test-and-receipt follow-up only. No older PR is approved for an automatic merge.
- Require independent review or approval: #17, #32, #34, #35, #36, #37, #38, #41, #46, #49. #34–#36 have replacement candidates but their branch-specific differences must not be discarded blindly. #37 now points at the updated release head; merging it into its older target is a separate decision. #41 currently reports a merge conflict. #46 can be mechanically mergeable while its pinned deployment assumptions are obsolete for the new runtime.
- Duplicate/replaced candidates: #11, #12, #20, #33 (ancestry evidence in `prs.md`); #43, #44, #47, #48 (selected behavior integrated and tested in #50). Closure rationale is documented; no older PR was closed or wholesale merged.

PR #49 remains separate and was not deployed. Its isolated tests do not authorize changing TON/TRC20 receiving addresses. PR #17 refund scripts were not run. The known Telegram acceptance-before-local-ACK crash window remains documented in `report.md`.
