# PR55 — approved Production deployment receipt

Completed **2026-11-13 21:22:55 UTC / 2026-11-14 00:52:55 Asia/Tehran**, after the owner's explicit final merge/deployment approval. PR55 merged as `1ad1e9932d58522179b5379af8e60c270284190c`; reviewed head `3014ba4ae7c53af2827da7737d3628987a000913`. PR53 and PR54 were included and GitHub marked both merged. PR49 was subsequently closed as superseded, with its branch retained.

## Exact artifacts

Runtime source `a5773b36c043a4063f65c93a43f756ae38ac7fca` has no runtime difference from the merge in Backend app/migrations or Bot. The later commits contain tests and audit material.

| Service | Image | Docker image ID |
|---|---|---|
| Backend | `docker.io/library/dabarna-backend:final-a5773b3` | `sha256:95d43bb11df3125933592250bdb5c23c9c6abecffbd320859a97064060d08aa4` |
| Bot | `docker.io/library/dabarna-bot:final-a5773b3` | `sha256:fc9f74a517cf400d41995635169230d44b67cea66831abe742b70f93f67ded65` |

Transferred image archive: 87,758,848 bytes, SHA256 `13ab7fe0a59b7868a7210e4ba9aa62d9b4caafe57149ed2ca949730038f177e4`. Loaded IDs were verified before replacing services. No registry publication was necessary.

## Migration and preservation

Preflight found three LOBBY games, zero RUNNING games, and no lobby with two distinct buyers ready to start. Backend and Bot writers were stopped gracefully for the guarded migration to **20261113_0013**. MySQL and Redis were not restarted. Their existing container identities/start times remained unchanged.

A private logical backup of the actual database configured by Backend was gzip-validated before DDL: 205,792 bytes, SHA256 `042023b17c483a803b559728b95b29f62f39a93d1e39aa93d62a19d8948192a9`. Private backup, deployment script, Compose overlays and snapshots are retained in `/root/davarna-v2-release-backups/pr55-3014ba4-20261114`. Raw snapshots, environment files and the database backup must not be published.

All rows/counts/fingerprints of wallets, wallet transactions, card purchases, game cards, crypto invoices, deposit requests and withdrawal requests were unchanged by migration. Autopilot configuration, financial settings, active-game state and prior Telegram delivery ACKs were preserved. Five database triggers remain; only the intended draw-interval guard changed. The temporary trigger-creation server setting was restored in `finally`. Six offline deployment-guard tests verified refusal of running/ready games and restoration after success/failure.

Backend and Bot use their original runtime environments, mounts and commands with the new images. No financial destination, wallet balance, refund, Autopilot toggle or manual game transition was requested or performed.

## Post-deployment checks

At 21:27 UTC all four services were healthy, restart counts zero. Backend/Bot startup logs contained no ERROR/CRITICAL or Traceback. Autopilot and notifier startup were observed. Auto-draw has no startup log; absence of that log is not a claim that a real new draw cycle was exercised.

Internal HTTP, server-side public HTTPS, and workstation public HTTPS all verified `/health/db` and `/mini/` as 200. The exact HTML, JavaScript, CSS and clock-module SHA256 values matched the built artifact. Unauthenticated admin dashboard and automation timeline requests returned 401.

The first public probe using Python urllib returned 403. The same endpoints using server curl and independent workstation curl returned the expected statuses and exact asset hashes. The probe client was changed, not the expected assertions or server authorization/network configuration. The precise cause of the client-dependent 403 was not established.

Evidence: [deployment-verification.json](deployment-verification.json), [public-verification.json](public-verification.json), [financial-gates.json](financial-gates.json), [candidate-images.json](candidate-images.json).

## Actual limits

- Production and test **destination-rotation gates remain false**. Owner management code is deployed; actual destination activation has not been enabled or tested in Production.
- There were still three LOBBY games and no RUNNING game at verification. Isolated complete game cycles passed; a natural complete game cycle on the newly deployed version has not yet been observed. No real game was started to manufacture this evidence.
- No test message was sent to real Telegram users, and no real purchase/transfer/refund was used as a smoke test. Long-running load and real provider/Telegram outage recovery are not claimed tested.
- Later requests to make minimum players editable or simplify duplicate rest controls are separate follow-up changes, not part of this deployed artifact.

## Rollback

Retain the previous images, private runtime snapshots, database backup and migration logs. Before any new writer starts, the deployment recovery path restores the original guard, removes only the newly added entirely-null readiness column, and restores the migration version when needed. After new application writers start, do not blindly downgrade: first check for newly used 2/3/4-second games/configuration and any financial-state change. Compatible old images can retain additive schema only after those checks. A schema downgrade refuses fast-game history; never delete financial/game history to make rollback pass.

After any future real address rotation, preserve historical invoice destinations and scanning of retired/current destinations; disabling versioned routing blindly can revive stale environment addresses. That requires a separately reviewed financial rollback. No Production rollback or fault injection was performed in this successful rollout.
