# Game transparency, connected purchase and tracking refresh

Players can select a dashboard game, top up and return to that game, purchase once and open the purchased cards. A changed selection during the balance request cannot purchase another game. Explicit snapshot requests discard stale responses.

The Mini App now shows winners from exactly the latest five completed games, ordered by actual end time. A separate authenticated read-only endpoint validates winner cards against recorded game/user ownership and the saved LINE/FULL_CARD/LEGACY rule. Winner identities are masked, and card references are displayed. Missing/invalid per-card shares remain unknown; event totals are never substituted for individual shares. The display distinguishes recorded prize events from private wallet-credit receipts. It replaces the earlier recent-game totals that could be inferred from prize pools or default splits.

Tracking Refresh reads changed form values, keeps the active detail record, and does not start an unfiltered history request when no search was submitted or the edited query is empty. Explicit Search still allows browsing accessible records. API ownership enforcement is unchanged.

Public prize notices now use separate persistent delivery ACKs for the results topic. Failed sends are retried independently of private/admin prize processing. Pending delivery survives restart. Existing legacy prize markers avoid historical replays during upgrade. There is still a crash window between Telegram accepting a message and saving its local ACK; exactly-once delivery is not claimed. Existing private-message and called-number delivery semantics are unchanged.

## Validation executed

- Backend: 313 tests, PASS, 4 environment-gated tests skipped in this run.
- Disposable local MySQL: 30 tests PASS (fresh migration and repeat, lifecycle/finance/concurrency, crypto destinations, dashboard RBAC). No real database involved.
- Bot: 66 tests PASS, including failed prize send, restart recovery, duplicate suppression and legacy replay avoidance.
- 12 existing JavaScript suites PASS.
- Six browser suites PASS: results/tracking, connected purchase, bilingual UI, previous UX (27 screenshots), English admin Autopilot, English owner crypto controls. Real application assets, mocked APIs, no real purchases or Telegram test messages.
- Syntax, generated locale drift and git whitespace checks PASS. Cache versions updated for both languages and tracking modules.

Initial failures were addressed: outdated expected asset version in one test was updated to the actual blue theme (other assertions retained); local Docker was initially stopped; temporary MySQL authentication/readiness needed native-client cache warmup and TCP readiness instead of the bootstrap socket. Fresh isolated rerun passed all scenarios.

## Deployment

Owner explicitly authorized publication and, in reply to the specific restart question, completion including one bot-service replacement. Backend, MySQL, Redis and Autopilot must remain running unchanged. No production migrations or financial configuration changes.

UI: use the existing dedicated sidecar model; add `/mini-api/games/recent-results` to its read-only routes and nginx map. Serve all updated FA/EN assets together. Bot: build from the exact current immutable bot image, replacing only notifier.py. Preserve environment, network, ports, health check and storage mount. Keep the stopped previous container and previous UI route map for rollback. Do not replay historical winners or send test announcements to live users.

PR66 remains separate; no claim is made that every possible Mini App bug is eliminated or that physical Telegram devices have been exhaustively tested. Live post-deployment evidence belongs in the release notes.
