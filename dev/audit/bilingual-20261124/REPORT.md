# Bilingual Mini App — 2026-11-24

Persian remains the default. Settings > Language / زبان selects Persian (RTL) or English (LTR). The choice is stored on this device. Switching reloads the page after confirmation, preserving query parameters and tracking links. Unsaved form entries are discarded only after confirmation.

English covers the source-owned player and admin interface, games, cards, wallet controls, tracking, countdowns and dialogs. The catalog contains 1666 reviewed source segments. Currency remains toman; English uses Latin digits and Gregorian formatting. Card coordinates and API data are unchanged. Free-form names, review reasons, admin messages, addresses and identifiers are not machine translated.

## Implementation and maintenance

Persian assets are the source of behavior. `dev/tools/build-mini-locales.mjs` compiles English presentation literals using Acorn; regexes, object keys and Persian API matching predicates remain intact. English rule validation explicitly matches the English inconsistent-rule result. Generated assets are committed so image builds do not require an additional frontend build step.

Run `npm ci --prefix dev/tools`, then `npm run locales --prefix dev/tools` after editing source or `backend/app/static/mini/locales/en.json`. Run `npm run check --prefix dev/tools` to reject stale generated assets. Do not edit generated files directly. `server-labels.en.mjs` only handles allowlisted system fields and anchored server notification templates; arbitrary values remain original.

## Executed validation

- All 12 existing `backend/tests/js/*.mjs` suites: PASS.
- `dev/qa/bilingual.test.mjs`: PASS (three rules, mismatched layout, invalid FULL_CARD Tourna, individual prize amounts, notification templates, unchanged private field values).
- `dev/qa/bilingual-browser.mjs`: PASS (real local assets, mock APIs; LTR/RTL, games, tracking, 320/390/1440px in light/dark, cancel/accept language switch, saved preference, zero API mutations, zero page errors).
- Existing `dev/qa/remaining-ux-browser.mjs`: PASS; 27 screenshots, zero page errors, zero mutation requests.
- Generator --check, JS syntax and git diff --check: PASS.
- Initial browser test failed because it attempted to select a hidden settings field. The test now opens settings as a user would; assertions were retained.
- Visual inspection of English mobile light screenshot: readable header, language picker and game cards, no horizontal overflow.

## Release gates and limits

This branch is based on production commit 67c9d3c. PR66 remains a separate security audit change; coordinate both before the next release. This change is not deployed. No production database, game, financial destination, worker or container was changed.

Keep this PR draft pending a full English admin walkthrough and review of dynamic server responses outside the covered notification/receipt/tracking schemas. Unknown server strings intentionally fall back to their original text instead of guessing. Telegram bot message localization is outside this Mini App feature. Actual Telegram mobile behavior and OS font differences still require acceptance testing.

For deployment, route en.html, app.en.js, experience.en.mjs, tracking.en.mjs, automation-clocks.en.mjs, locale-en.mjs, server-labels.en.mjs, language.js and language.css to the same new UI image as index.html. Verify every asset returns the right MIME type, preserve Telegram query/hash data, and smoke both languages. Existing production proxy routing only lists older assets and must be extended. Do not activate the new index before all locale assets are available. Rollback restores the prior image and complete route map atomically; device language preferences are inert in the old UI.
