# Approved nonfinancial Production deployment — 2026-11-13

PR [#52](https://github.com/MR-P3Y/dabarna/pull/52) was merged and deployed after separate explicit owner approvals. This receipt supersedes the prerelease status in the earlier audit commits. Financial PR [#53](https://github.com/MR-P3Y/dabarna/pull/53) remains Draft and was not deployed.

- Release merge: `a7f3883ca0dcc4f98f0de2f84c0dbbb03088cba6` on `release/davarna-v1-candidate-20261109`.
- Reviewed head: `b52b29362cb805702cab85cee8b0badd6d679b92`; merged tree verified identical.
- Runtime image source: `4f1b0fdab31f5fa9134fd0a3dd5a8c423afafb80`; subsequent candidate commits contain audit evidence only.
- Successful rollout: **2026-11-13 12:53:21 UTC / 16:23:21 Asia/Tehran**.
- Independent health/log/monitor verification: **12:59:19 UTC**; public HTTPS verification: **13:01:01 UTC**.

## Images and deployment scope

| Service | Deployed tag | Exact image ID |
|---|---|---|
| Backend | `dabarna-backend:remaining-4f1b0fd` | `sha256:64556bf2edb7babdb5b7885825ec325d3905c4141931e31f4a94fb245e31812b` |
| Bot | `dabarna-bot:remaining-4f1b0fd` | `sha256:d947a81ae03c8d79fa6bca865fd65358886e28a6458f8a9993cc5aadcd97f96c` |

These are the tested images, transferred without rebuilding. Transfer archive: 86,610,944 bytes, SHA-256 `b6bc436e9e46a315e09bdb7c4fc50cca2ac9049e099a0b71451a442da505a897`. Source verification covered 90 Backend and 85 Bot files. The real Compose chain for each service was retained. Only Backend/Bot were recreated, using direct Uvicorn startup without migration or seed execution. The server source checkout was not reset.

The approved monitor replacement was installed at `/usr/local/sbin/davarna-monitor.sh`, SHA-256 `9197f47016632a323a8f4d76116c58df3fb3838e293a425860b8e95e90dfbff9`, preserving ownership and mode 0750. Its existing five-minute cron schedule remained unchanged. A natural scheduled run updated the monitor log and persistent notification fingerprint after installation. No synthetic Telegram notification was sent. Offline Bash tests provide deduplication/retry coverage; this observation alone does not prove every live alert transition.

## Checks and preserved state

Machine-readable, sanitized observations are in [deployment-verification.json](deployment-verification.json).

- Backend, Bot, MySQL and Redis: healthy, restart count zero. No ERROR/CRITICAL or traceback lines in new Backend/Bot container logs through the independent observation.
- MySQL/Redis retained their original containers and August 16 startup times; neither was restarted.
- Schema remained `20261108_0012`. Runtime environment and mounts, Autopilot settings and financial settings were compared against the predeployment snapshot and retained.
- Existing persistent Bot delivery ACK markers were retained or advanced. No ACK reset was performed.
- `/health/db`, `/mini/`, `/mini/app.js`, `/mini/experience.mjs`, `/mini/ux-v2.css`: 200. The four static responses matched the exact tested image bytes. JavaScript module MIME was correct. Unauthenticated `/mini-api/admin/ops-dashboard`: 401.
- The same public HTTPS paths were checked from the local workstation with real GET requests: expected statuses and four exact asset hashes passed. A preceding server-origin public HTTP probe received 403 on all paths; the independently successful workstation checks distinguish that vantage restriction from an application asset failure. No proxy/WAF configuration was changed.
- A fresh logical database backup used a single transaction without table locks: compressed size 208,661 bytes, SHA-256 `0b2dd80c63ef0c2ccade16170ce6037702d28dd229f62a670fbbca0d263f32b3`. Backup contents and raw environment/configuration snapshots are root-private and are not included in Git.
- No real purchases, wallet edits, refunds, destination changes, active-game actions, Autopilot toggles or database migrations were performed.

## First attempt and verified recovery

The first attempt reached the new Backend, then failed the static hash guard before starting the new Bot. Automatic rollback restored the previous Backend/Bot and verified health. The monitor had not yet been replaced. This failure is retained in the private attempt log, not represented as a successful first rollout.

The mismatch came from Git archive checkout bytes using CRLF while the initial HTTP expectation used LF Git blobs. The application content was unchanged. Validation was corrected to compare HTTP responses against the exact archive bytes used to build and test the images, while separately requiring normalized bytes to equal the merged Release blobs. No hash assertion was removed. The four HTTP asset checks were first rerun successfully against the candidate in an isolated, network-disabled container without starting workers, and then passed in the second Production attempt. Public HTTPS later matched those same hashes.

## Regression evidence and limits

The prerelease [report](report.md) contains executed tests: 186 Backend tests plus 44 subtests, 65 Bot tests plus 12 subtests, all 10 JavaScript suite files, mobile/desktop Chrome scenarios, and 5 offline monitor tests. The Backend/Bot suites also passed inside these exact candidate images. Two opt-in MySQL tests were skipped in the primary Backend run; separately executed MySQL scenarios and their branch scope are explicitly listed in that report. Test groups overlap and should not be summed into one total.

No synthetic end-to-end paid game or real Telegram winner message was run. There were no RUNNING games at preflight; a complete live Autopilot/game lifecycle was not observed. Worker settings were preserved, not enabled for a test. Existing general/level topic routes remain; a new dedicated start-topic ID is not configured. Read state is per account on the same device. Telegram delivery remains at-least-once across a crash between acceptance and durable ACK.

## Rollback retained

Rollback images remain available:

- Backend `dabarna-backend:rc-850a6db`: `sha256:e713ff8b7a43a800549b94048efba403ee6e7314a28ae72a1cd7a73e33cf7731`.
- Bot `dabarna-bot:rc-850a6db`: `sha256:9f2bad21e0f3884a7f31151accb3a06c5229991194afdc5685af22751fa1d47b`.

The restricted release backup directory retains per-service Compose configurations, rollback overlays, original monitor, ACK baseline, database dump, first-attempt evidence and second-attempt results. Rollback stops Bot, restores the pinned previous Backend without migration/seed, checks health, then restores Bot and checks health/HTTP. Restore the old monitor with its original ownership/mode if needed. Do not restore or truncate the live database, ledger, wallet, volumes or current ACK state as part of an application rollback. No cleanup of protected images, backups or history was performed.

This documentation-only follow-up does not change runtime code, repeat deployment, merge PR #53, or authorize financial operations.
