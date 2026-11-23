# Header and elevation polish — 2026-11-23

Preserve the blue palette. Group identity/balance, game status and three consistent icon-and-label actions. Preferences open without shifting the action row. Shared layered shadows distinguish panels, buttons and elevated dialogs in both themes.

Validation: 11 JavaScript test files passed. Real-assets offline browser acceptance passed with 26 screenshots, zero page errors and zero mutations. Header checks cover 320/390/1440 widths in both themes, touch targets >=44px, horizontal overflow, action alignment, stable layout when preferences open, and existing theme/sound/inbox/tracking controls. Initial browser run exposed a preferences stacking issue; fixed header stacking and reran successfully. Screenshots use synthetic data.

## Release and rollback

UI-only image based on the verified PR63 image, with an unchanged minimal player/tracking entrypoint. Stage on a new private listener, verify asset hashes and authentication, then validate and gracefully reload nginx routing. Preserve the previous UI service and saved nginx configuration for rollback. No migration or business-logic changes; existing backend, bot, MySQL and Redis containers must retain their IDs and start times. Restore the saved nginx configuration and reload nginx if post-deployment verification fails.
