# Telegram controls and game haptics

Notification overlay respects Telegram system and content safe-area CSS variables (with browser env fallback) and responds to fullscreen/orientation updates. Its close target remains at least 44px and is labelled specifically for notifications.

Vibration toggle shows on/off text, persists preference and requests one sample when enabled. Number and countdown feedback use the same guarded Telegram-first helper with browser fallback. API acceptance does not guarantee physical vibration.

Validation: 12 JavaScript test files passed. Offline real-assets browser acceptance passed with 27 screenshots, zero page errors and mutation requests. Simulated portrait notch + Telegram controls, landscape side insets and return to non-fullscreen; actual close click and bounds assertions passed. Haptics tests cover disabled/background/disabled cue states, persistence, one sample, Telegram priority and failing/absent browser APIs. Initial countdown unit harness needed the extracted shared helper; loaded actual helper and reran all assertions successfully. Physical-device haptics were not tested.

Reference: https://core.telegram.org/bots/webapps (SafeAreaInset, ContentSafeAreaInset, HapticFeedback).

Deploy: UI-only sidecar from verified PR64 image, compare manifests, preserve core containers, validate nginx and gracefully reload routes. Rollback restores saved nginx config to previous UI listener. No API/database/financial/game engine changes.
