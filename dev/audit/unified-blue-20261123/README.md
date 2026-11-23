# Unified blue theme acceptance — 2026-11-23

All Mini App palette literals are centralized in theme.css. Legacy component variables now resolve to semantic surface, text, blue action, warning and danger tokens. Layout and business logic are unchanged. Called numbers retain a distinct blue fill and border. QR backgrounds remain white.

Executed locally against actual HTML/CSS/JS, mocked GET APIs, no real Telegram messages or financial writes:
- 11 JavaScript test files passed (node --test backend/tests/js/*.mjs).
- remaining-ux-browser.mjs passed: 18 captures, zero JS errors and mutation requests; 320/390/1440 widths, both themes, inbox, winners, card focus, tracking, wallet and dashboard.
- autopilot-pacing-browser.mjs passed: timers, server-pending and stale states, polling coalescence, editable countdown, rule-specific draw speeds; light/dark settings captures, zero writes.
- All Mini App CSS parsed with tinycss2 without errors; semantic text pairs >= 4.5:1 contrast in both themes.
- Visual inspection: tracking, wallet, game card focus, admin settings. Captures use synthetic data; this is not a real Telegram device test.

## Release / rollback
Build a new UI-only image from the verified PR62 image. Preserve minimal read-only tracking/player entrypoint and core containers. Route theme.css and styles.css alongside existing Mini App assets to the new private listener. Check nginx configuration before graceful reload, then compare public and origin asset hashes and authentication checks. Save original nginx configuration; restore it and reload nginx if any check fails. No migration, financial action, game operation or existing container restart is needed.
