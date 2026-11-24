# Connected game journey and Telegram announcement audit

The player can move from a dashboard game to its purchase form, top up and return to the same game, then open the purchased cards or follow that game. The purchase path is above the live number panel. The purchase confirmation survives snapshot refresh and identifies the game and purchase. Both Persian and English are supported.

A pending purchase now captures its game ID, rejects a changed selection during the balance check, and suppresses concurrent duplicate invocations. Wallet balance calculations, price, qty payload, backend payment logic and idempotency implementation are unchanged. Navigation never purchases automatically. A stale explicit snapshot response cannot replace a newer selection.

Executed tests: new Persian/English browser journey with mocked purchases (navigation without writes, one POST for two invocations, correct game ID, receipt and card link, request failure unlock, changed selection and running game); no horizontal overflow at 320/390/1440; existing bilingual browser suite; existing Persian UX browser suite (27 screenshots); all 12 existing JS suites; generator drift, syntax and whitespace checks. Initial test attempted an assertion before the asynchronous snapshot arrived; it now waits for the actual rendered navigation before asserting.

## Live Telegram audit (read-only)

Live bot config: announce=3; game_start unset (falls back to announce=3); game lanes LOW=6, MEDIUM=8, HIGH=10; live numbers=12; results=14. Persisted event markers exist. Live AST hashes for prize handling, lifecycle, number notices and notifier loop match reviewed repository source.

- Creation/open purchasing: announce topic.
- Autopilot countdown: game lane and announce, subject to configured destination/eligibility and deadline.
- Actual start: announce (or dedicated game_start if set), plus lane for system games.
- Called numbers: live topic.
- Prize winners: results topic; personal amount in winner DM; administrative report separately.
- End/result: results topic.
- Separate loser-by-loser notice: not present in inspected path.

Cannot promise every message is delivered: `_queue_prize_notifications` ignores the boolean result of results-topic send, and the outer loop advances PRIZE_COL/PRIZE_ROW processed markers anyway. Direct messages are queued before actual delivery, not individually durably acknowledged. Number notices have a similar processed-vs-delivered distinction. Start/end lifecycle delivery has per-destination persistent ACK, but legacy markers and crash-between-send-and-ACK mean it is not proof of exactly-once historical delivery.

No Telegram messages were sent during this audit. No bot configuration, destination, database or live game was changed. These findings are reported rather than silently changing live notification behavior. A separate reliability change should use destination-specific durable delivery records, tests for failed sends/restarts and recovery rules that do not replay historical winners to users.

UI implementation is committed for review; not merged or deployed by this task. Production remains the bilingual release prod-2026-11-24.1.
