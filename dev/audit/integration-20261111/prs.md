# حسابرسی PRها

| PR | وضعیت | وابستگی | ریسک | اقدام پیشنهادی | دلیل |
|---|---|---|---|---|---|
| [#11](https://github.com/MR-P3Y/dabarna/pull/11) | در تاریخچه Release | main | متوسط | بستن پس از تأیید جایگزینی | کد در تاریخچه مبنای نسخه جاری موجود است |
| [#12](https://github.com/MR-P3Y/dabarna/pull/12) | در تاریخچه Release | feature/autopilot-foundation-20261031 | متوسط | بستن پس از تأیید جایگزینی | کد در تاریخچه مبنای نسخه جاری موجود است |
| [#17](https://github.com/MR-P3Y/dabarna/pull/17) | مسیر مستقل | feature/ui-ux-refresh-tambola-v2-20261106 | بالا | تأیید مالی جداگانه | عملیات مالی و Migration مستقل؛ مجوز اجرای واقعی ندارد |
| [#20](https://github.com/MR-P3Y/dabarna/pull/20) | در تاریخچه Release | feature/ui-ux-refresh-tambola-v2-20261106 | متوسط | بستن پس از تأیید جایگزینی | کد در تاریخچه مبنای نسخه جاری موجود است |
| [#32](https://github.com/MR-P3Y/dabarna/pull/32) | مسیر مستقل | release/combined-forum-mini-candidate-20261107 | بالا | تأیید مالی جداگانه | عملیات مالی و Migration مستقل؛ مجوز اجرای واقعی ندارد |
| [#33](https://github.com/MR-P3Y/dabarna/pull/33) | در تاریخچه Release | release/combined-forum-mini-candidate-20261107 | متوسط | بستن پس از تأیید جایگزینی | کد در تاریخچه مبنای نسخه جاری موجود است |
| [#34](https://github.com/MR-P3Y/dabarna/pull/34) | مسیر مستقل | fix/game-forum-notices-rule-routing-20261109 | بالا | بازبینی تغییرات اختصاصی | Merge کلی ممکن است UI قدیمی یا تغییر مالی وارد کند |
| [#35](https://github.com/MR-P3Y/dabarna/pull/35) | مسیر مستقل | release/combined-forum-mini-candidate-20261107 | بالا | بازبینی تغییرات اختصاصی | Merge کلی ممکن است UI قدیمی یا تغییر مالی وارد کند |
| [#36](https://github.com/MR-P3Y/dabarna/pull/36) | مسیر مستقل | release/combined-forum-mini-candidate-20261107 | بالا | بازبینی تغییرات اختصاصی | Merge کلی ممکن است UI قدیمی یا تغییر مالی وارد کند |
| [#37](https://github.com/MR-P3Y/dabarna/pull/37) | در تاریخچه Release | release/combined-forum-mini-candidate-20261107 | متوسط | حفظ مبنای Release | شامل Merge شماره ۴۵ و V1.3 |
| [#38](https://github.com/MR-P3Y/dabarna/pull/38) | مسیر مستقل | release/combined-forum-mini-candidate-20261107 | بالا | بازبینی تغییرات اختصاصی | Merge کلی ممکن است UI قدیمی یا تغییر مالی وارد کند |
| [#41](https://github.com/MR-P3Y/dabarna/pull/41) | مسیر مستقل | feature/superadmin-live-dashboard-v11-20261109 | بالا | تأیید مالی جداگانه | عملیات مالی و Migration مستقل؛ مجوز اجرای واقعی ندارد |
| [#43](https://github.com/MR-P3Y/dabarna/pull/43) | بخشی در runtime | release/superadmin-command-ui-v12-20261110 | بالا | جایگزینی با Integration | Guard و dashboard در overlay واقعی یافت شد |
| [#44](https://github.com/MR-P3Y/dabarna/pull/44) | بخشی در runtime | hotfix/auto-draw-worker-start-guard-20261110 | بالا | جایگزینی با Integration | Guard و dashboard در overlay واقعی یافت شد |
| [#46](https://github.com/MR-P3Y/dabarna/pull/46) | مسیر مستقل | release/davarna-v1-candidate-20261109 | بالا | به‌روزرسانی پیش‌شرط‌های انتشار | اسکریپت به ایمیج‌های انتشار قبلی مقید است |
| [#47](https://github.com/MR-P3Y/dabarna/pull/47) | اصلاح‌شده در Integration | feature/autopilot-readiness-system-games-20261110 | بالا | جایگزینی پس از تکمیل تأیید نهایی | تست‌های متن، کارت و countdown اصلاح و اجرا شدند |
| [#48](https://github.com/MR-P3Y/dabarna/pull/48) | اصلاح‌شده در Integration | feature/autopilot-game-start-countdown-20261110 | بالا | جایگزینی پس از تکمیل تأیید نهایی | تست‌های متن، کارت و countdown اصلاح و اجرا شدند |
| [#49](https://github.com/MR-P3Y/dabarna/pull/49) | مسیر مستقل | feature/superadmin-command-center-v12-20261110 | بالا | تأیید مالی جداگانه | عملیات مالی و Migration مستقل؛ مجوز اجرای واقعی ندارد |

## PR #11

Head بررسی‌شده 03220fa47b7fb1d402714fe675d869ccd63797bb. عضو تاریخچه 1346712 = True.

- backend/app/static/mini/app.js node --check — exit 0. 
- backend/tests/test_game_commission.py — exit 0. .....                                                                 [100%] 5 passed, 3 subtests passed in 1.44s

## PR #12

Head بررسی‌شده c8f514e7c1b5edc862e3445d0808a982aff1320d. عضو تاریخچه 1346712 = True.

- backend/app/static/mini/app.js node --check — exit 0. 
- backend/tests/test_bingo_v2.py — exit 0. .........                                                                [100%] 9 passed in 0.19s
- backend/tests/test_game_auto_draw.py — exit 0. .....                                                                    [100%] 5 passed in 1.38s
- backend/tests/test_game_commission.py — exit 0. .....                                                                 [100%] 5 passed, 3 subtests passed in 1.83s
- backend/tests/test_game_v2_dispatch.py — exit 0. .....                                                                    [100%] 5 passed in 1.54s

## PR #17

Head بررسی‌شده 0622f0c51649fb8fa41f3e61038687757c297593. عضو تاریخچه 1346712 = False.

- dev/ops/rehearse-game84-cancel.sh bash -n — exit 0. 
- dev/ops/run-game84-refund-notice.sh bash -n — exit 0. 

## PR #20

Head بررسی‌شده 22ddf0f60e5eb0e56462503597679d0541efe229. عضو تاریخچه 1346712 = True.

- backend/app/static/mini/app.js node --check — exit 0. 
- dev/ops/prepare-low-and-publish-forum-guide-20261108.sh bash -n — exit 0. 
- dev/release/activate-low-one-round-20261108.sh bash -n — exit 0. 
- dev/release/close-low-one-round-20261108.sh bash -n — exit 0. 
- dev/release/deploy-combined-forum-mini-20261107.sh bash -n — exit 0. 
- dev/release/stage-combined-forum-mini-20261107.sh bash -n — exit 0. 
- dev/release/test-low-autopilot-isolated-20261108.sh bash -n — exit 0. 
- dev/release/test-low-autopilot-stage2-isolated-20261108.sh bash -n — exit 0. 
- dev/release/test-mini-finance-reject-reasons-20261108.sh bash -n — exit 0. 
- backend/tests/test_mini_deposit_rejection_reason.py — exit 0. -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html 10 passed, 5 warnings in 2.44s
- backend/tests/test_mini_superadmin_ui_contract.py — exit 0. ......                                                                   [100%] 6 passed in 0.05s
- backend/tests/test_withdraw_rejection_reason.py — exit 0. ....                                                                     [100%] 4 passed in 1.52s

## PR #32

Head بررسی‌شده 5d03acada4418a8340ad9df67176e895cf7ce79c. عضو تاریخچه 1346712 = False.

- backend/app/static/mini/app.js node --check — exit 0. 
- dev/release/test-crypto-30-final-gate-20261109.sh bash -n — exit 0. 
- dev/release/test-crypto-challenge-mysql-20261109.sh bash -n — exit 0. 
- dev/release/test-crypto-destinations-mysql-20261109.sh bash -n — exit 0. 
- dev/release/test-crypto-drafts-mysql-race-20261109.sh bash -n — exit 0. 
- dev/release/test-crypto-late-queue-mysql-20261109.sh bash -n — exit 0. 
- dev/release/test-crypto-settlement-mysql-20261109.sh bash -n — exit 0. 
- backend/tests/test_crypto_address_rotation_validation.py — exit 0. ..........                                                               [100%] 10 passed in 0.04s
- backend/tests/test_crypto_chain_pagination.py — exit 0. .........                                                                [100%] 9 passed in 0.21s
- backend/tests/test_crypto_destination_confirmations.py — exit 0. -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html 9 passed, 1 warning in 2.69s
- backend/tests/test_crypto_destination_drafts.py — exit 0. -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html 8 passed, 1 warning in 2.69s
- backend/tests/test_crypto_invoice_expiry_safety.py — exit 0. ...                                                                      [100%] 3 passed in 1.49s
- backend/tests/test_crypto_late_payment_queue.py — exit 0. -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html 11 passed, 1 warning in 2.27s
- backend/tests/test_crypto_late_payment_review.py — exit 0. -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html 12 passed, 1 warning in 1.87s
- backend/tests/test_crypto_rotation_multi_address.py — exit 0. .....                                                                    [100%] 5 passed in 0.87s
- backend/tests/test_crypto_rotation_ui_contract.py — exit 0. ....                                                                     [100%] 4 passed in 0.03s
- backend/tests/test_crypto_worker_scan_recovery.py — exit 0. ....                                                                     [100%] 4 passed in 0.88s

## PR #33

Head بررسی‌شده 779507df2b2870376848df5872a7660f5ae53638. عضو تاریخچه 1346712 = True.

- backend/tests/test_game_forum_lifecycle_contract.py — exit 0. ......                                                                   [100%] 6 passed in 0.75s

## PR #34

Head بررسی‌شده a7785d63473d0160aa5e807bb7477e8089f5ab60. عضو تاریخچه 1346712 = False.

- dev/release/check-v1-readiness-20261109.sh bash -n — exit 0. 
- dev/release/test-telegram-lifecycle-ack-20261109.sh bash -n — exit 0. 
- davarna-bot/tests/test_lifecycle_delivery_ack.py — exit 0. ...............                                                          [100%] 15 passed in 0.93s

## PR #35

Head بررسی‌شده bda139f36eb36a4d4c83cacde48f750c6064827c. عضو تاریخچه 1346712 = False.

- dev/release/davarna-v1-rc-readonly-gate-20261109.sh bash -n — exit 0. 
- dev/release/test-telegram-lifecycle-ack-20261109.sh bash -n — exit 0. 
- backend/tests/test_game_forum_lifecycle_contract.py — exit 0. ......                                                                   [100%] 6 passed in 0.63s
- davarna-bot/tests/test_lifecycle_delivery_ack.py — exit 0. ...............                                                          [100%] 15 passed in 0.74s

## PR #36

Head بررسی‌شده edccb499c402e1b224aa1eff2db2977b07f3acea. عضو تاریخچه 1346712 = False.

- dev/release/test-telegram-lifecycle-ack-20261109.sh bash -n — exit 0. 
- dev/release/v1-rc-preflight-readonly-20261109.sh bash -n — exit 0. 
- backend/tests/test_game_forum_lifecycle_contract.py — exit 0. ......                                                                   [100%] 6 passed in 0.59s
- davarna-bot/tests/test_lifecycle_delivery_ack.py — exit 0. ...............                                                          [100%] 15 passed in 0.57s

## PR #37

Head بررسی‌شده 13467120109c941bc1f4a5b4e88be1fdabddb479. عضو تاریخچه 1346712 = True.

- backend/app/static/mini/app.js node --check — exit 0. 
- backend/tests/js/test_superadmin_dashboard_v11.mjs node --check — exit 0. 
- backend/tests/js/test_superadmin_sections_v13.mjs node --check — exit 0. 
- dev/release/build-superadmin-ui-v12-20261110.sh bash -n — exit 0. 
- dev/release/build-superadmin-v11-candidate-20261109.sh bash -n — exit 0. 
- dev/release/deploy-superadmin-ui-v12-20261110.sh bash -n — exit 0. 
- dev/release/test-davarna-v1-rc-offline-20261109.sh bash -n — exit 0. 
- dev/release/test-superadmin-v11-20261109.sh bash -n — exit 0. 
- dev/release/test-telegram-lifecycle-ack-20261109.sh bash -n — exit 0. 
- backend/tests/test_game_forum_lifecycle_contract.py — exit 0. ......                                                                   [100%] 6 passed in 0.57s
- backend/tests/test_mini_ops_dashboard_rbac_http.py — exit 0. -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html 4 passed, 8 warnings, 4 subtests passed in 3.82s
- davarna-bot/tests/test_lifecycle_delivery_ack.py — exit 0. ...............                                                          [100%] 15 passed in 0.77s
- backend/tests/js/test_superadmin_dashboard_v11.mjs — exit 0. ℹ todo 0 ℹ duration_ms 247.2374
- backend/tests/js/test_superadmin_sections_v13.mjs — exit 0. ℹ todo 0 ℹ duration_ms 136.591

## PR #38

Head بررسی‌شده 2b23083e8dd7fb1c60151ff602a3f6144421b2be. عضو تاریخچه 1346712 = False.

- dev/release/test-telegram-lifecycle-ack-20261109.sh bash -n — exit 0. 
- dev/release/v1-readiness-only-20261109.sh bash -n — exit 0. 
- backend/tests/test_game_forum_lifecycle_contract.py — exit 0. ......                                                                   [100%] 6 passed in 0.61s
- davarna-bot/tests/test_lifecycle_delivery_ack.py — exit 0. ...............                                                          [100%] 15 passed in 0.91s

## PR #41

Head بررسی‌شده f0a98a4cd8aff51c22d9509402a4ab8d53815cdf. عضو تاریخچه 1346712 = False.

- backend/app/static/mini/app.js node --check — exit 0. 
- backend/tests/js/test_superadmin_dashboard_v11.mjs node --check — exit 0. 
- dev/release/bootstrap-zero-km-owner-20261110.sh bash -n — exit 0. 
- dev/release/build-zero-km-v12-v13-candidate-20261110.sh bash -n — exit 0. 
- dev/release/cleanup-crypto-test-invoices-guarded-20261110.sh bash -n — exit 0. 
- dev/release/preflight-zero-km-cutover-readonly-20261110.sh bash -n — exit 0. 
- dev/release/prepare-zero-km-persistent-mysql-20261110.sh bash -n — exit 0. 
- dev/release/stage-zero-km-new-crypto-addresses-20261110.sh bash -n — exit 0. 
- dev/release/start-zero-km-isolated-backend-preview-20261110.sh bash -n — exit 0. 
- dev/release/test-clean-launch-fresh-db-20261110.sh bash -n — exit 0. 
- dev/release/test-superadmin-command-v12-20261110.sh bash -n — exit 0. 
- dev/release/test-wallet-rotation-mysql-disposable-20261110.sh bash -n — exit 0. 
- dev/release/verify-wallet-release-image-readonly-20261110.sh bash -n — exit 0. 
- dev/release/verify-wallet-rotation-release-candidate-20261110.sh bash -n — exit 0. 
- backend/tests/test_crypto_destination_match_isolated.py — exit 0. -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html 5 passed, 5 warnings in 1.29s
- backend/tests/test_crypto_destination_version_proto.py — exit 0. .....                                                                    [100%] 5 passed in 1.19s
- backend/tests/test_crypto_historical_scan_gap_isolated.py — exit 0. ....                                                                     [100%] 4 passed in 2.15s
- backend/tests/test_crypto_late_replay_guard_isolated.py — exit 0. ....                                                                     [100%] 4 passed in 2.51s
- backend/tests/test_crypto_late_transfer_inbox_isolated.py — exit 0. ....                                                                     [100%] 4 passed in 1.20s
- backend/tests/test_crypto_multi_address_provider_contracts.py — exit 0. ...                                                                      [100%] 3 passed in 0.22s
- backend/tests/test_crypto_multi_address_worker_isolated.py — exit 0. ...                                                                      [100%] 3 passed in 1.73s
- backend/tests/test_crypto_production_rotation_gate_isolated.py — exit 0. ....                                                                     [100%] 4 passed in 1.23s
- backend/tests/test_crypto_rotation_readiness_isolated.py — exit 0. .....                                                                    [100%] 5 passed in 1.56s
- backend/tests/test_crypto_rotation_readiness_scan_isolated.py — exit 0. ....                                                                     [100%] 4 passed in 1.16s
- backend/tests/test_crypto_rotation_ton_memo_guard_isolated.py — exit 0. .....                                                                    [100%] 5 passed in 1.15s
- backend/tests/test_crypto_scan_observation_isolated.py — exit 0. ....                                                                     [100%] 4 passed in 0.94s
- backend/tests/test_crypto_scan_pagination_isolated.py — exit 0. ....                                                                     [100%] 4 passed in 0.14s
- backend/tests/test_mini_crypto_address_proposals.py — exit 0. -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html 18 passed, 15 warnings in 4.19s
- backend/tests/js/test_superadmin_dashboard_v11.mjs — exit 0. ℹ todo 0 ℹ duration_ms 123.8392

## PR #43

Head بررسی‌شده cf0317c5a6adf94be8656df3f2a06f86cc876678. عضو تاریخچه 1346712 = False.

- backend/app/static/mini/app.js node --check — exit 0. 
- dev/release/deploy-auto-clock-ui-20261110.sh bash -n — exit 0. 
- dev/release/recover-auto-draw-production-20261110.sh bash -n — exit 0. 
- backend/tests/test_auto_start_worker_disabled_guard.py — exit 0. ..                                                                       [100%] 2 passed in 1.22s

## PR #44

Head بررسی‌شده f6a8de5f616ce18e979f35ef8378e540d073467e. عضو تاریخچه 1346712 = False.

- backend/app/static/mini/app.js node --check — exit 0. 
- dev/release/activate-high-autopilot-20261110.sh bash -n — exit 0. 
- dev/release/activate-low-only-autopilot-20261110.sh bash -n — exit 0. 
- dev/release/activate-medium-autopilot-20261110.sh bash -n — exit 0. 
- dev/release/audit-autopilot-health-readonly-20261110.sh bash -n — exit 0. 
- dev/release/audit-game88-prize-replay-20261110.sh bash -n — exit 0. 
- dev/release/audit-rules-telegram-cross-surface-20261110.sh bash -n — exit 0. 
- dev/release/install-autopilot-monitor-20261110.sh bash -n — exit 0. 
- backend/tests/test_game_prize_replay_isolated_20261110.py — exit 0. ...                                                                      [100%] 3 passed in 1.13s
- davarna-bot/tests/test_notification_rule_consistency.py — exit 0. ......                                                                   [100%] 6 passed in 7.38s
- davarna-bot/tests/test_public_forum_notices.py — exit 0. ...                                                                      [100%] 3 passed in 7.17s

## PR #46

Head بررسی‌شده 254192d8b5a733931e1b29ac37a48f82363e34e5. عضو تاریخچه 1346712 = False.

- dev/release/deploy-superadmin-v13-20261110.sh bash -n — exit 0. 

## PR #47

Head بررسی‌شده 55a55027d9dd1b50e63d53112b2c45eff2ae9f7e. عضو تاریخچه 1346712 = False.

- backend/app/static/mini/app.js node --check — exit 0. 
- backend/tests/js/test_autopilot_start_countdown_v1.mjs node --check — exit 0. 
- backend/tests/test_autopilot_countdown_contract.py — exit 0. ....                                                                     [100%] 4 passed in 0.10s
- davarna-bot/tests/test_autopilot_countdown_notice.py — exit 0. .....                                                                    [100%] 5 passed in 6.73s
- backend/tests/js/test_autopilot_start_countdown_v1.mjs — exit 1. ✖ C:\Users\PEYMOON\AppData\Local\Temp\dabarna-pr-qa\47\backend\tests\js\test_autopilot_start_countdown_v1.mjs (147.7293ms)   'test failed'

## PR #48

Head بررسی‌شده 384be238c40246f72096b9720bd2cfe7bda9b9fe. عضو تاریخچه 1346712 = False.

- davarna-bot/tests/test_bot_rule_copy_20261110.py — exit 0. ........                                                                 [100%] 8 passed in 0.12s

## PR #49

Head بررسی‌شده 4794e556474edea9cc8a093437ed9ac1aca371af. عضو تاریخچه 1346712 = False.

- backend/app/static/mini/app.js node --check — exit 0. 
- dev/release/build-owner-wallet-bot-mini-candidate-20261110.sh bash -n — exit 0. 
- dev/release/test-owner-crypto-wallet-bot-mini-isolated-20261110.sh bash -n — exit 0. 
- dev/release/test-owner-wallet-staging-private-20261110.sh bash -n — exit 0. 
- dev/release/test-wallet-rotation-mysql-disposable-20261110.sh bash -n — exit 0. 
- backend/tests/test_crypto_production_rotation_gate_isolated.py — exit 0. .....                                                                    [100%] 5 passed in 1.08s
- backend/tests/test_owner_crypto_wallet_manager.py — exit 0. -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html 5 passed, 15 warnings in 5.13s
- davarna-bot/tests/test_crypto_wallet_owner_ui.py — exit 0. ....                                                                     [100%] 4 passed in 7.64s
- backend/tests/test_crypto_destination_version_proto.py — exit 0. .....                                                                    [100%] 5 passed in 1.79s
- backend/tests/test_mini_crypto_address_proposals.py — exit 0. -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html 18 passed, 15 warnings in 7.63s
- backend/tests/test_crypto_late_transfer_inbox_isolated.py — exit 0. ....                                                                     [100%] 4 passed in 0.94s
