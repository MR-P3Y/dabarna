# Quick release gate — Telegram forum notices (#33) and delivery ACK (#34)

**Status: release preparation only. Not a Production rollout.**

## Evidence already available

| Candidate | SHA | Test evidence |
| --- | --- | --- |
| PR #33 (rules, topic routing) | `779507df2b2870376848df5872a7660f5ae53638` | 6/6 offline tests PASS, Python syntax PASS |
| PR #34 (ACK / retry) | `2a95f2c4298c03e0fd0f8d150b476eead6b7c174` | 15/15 ACK/restart + 6/6 rules regressions PASS, syntax PASS |

GitHub reported both PRs **mergeable**, but no CI status checks or PR-triggered workflow runs were found on either SHA. Manual NODE2 evidence is not CI.

## One staging acceptance window — no Production writes

1. Confirm the **staging** bot token and test Telegram forum/chat are not Production. Do **not** guess a topic ID. Leave `USER_TOPIC_GAME_START_ID` unset unless the real test topic is known. No group renaming or automated topic creation.
2. Build a staging-only image from the pinned combined HEAD of #34 (includes #33), without replacing any running containers. Check imports/startup and use test-only game fixture/event IDs.
3. Deliver one synthetic `GAME_CREATED`, `GAME_STARTED`, `GAME_ENDED` flow to the verified test group, and verify user/admin destination, HTML, links, absence of unexpected duplicate, and correct LINE/FULL_CARD/LEGACY message text.
4. Simulate **one** failed send (disable test bot access temporarily / mocked Telegram API in staging) and restart the staging worker; pending event must replay once after recovery; a previously ACKed other destination must not replay.
5. Check persisted `storage/notif_state.json` ACK and pending keys, no loop of repeated sends, and no financial changes. Record PASS/FAIL and stop. No extra features.

**If staging bot and forum are unavailable**, mark real-send E2E **NOT TESTED** and stop at this gate; do not use the Production group as a substitute.

## Controlled rollout (requires separate explicit approval)

- Production preflight: backup the existing bot state and bot image digest/tag; verify storage mount and space, health, and current release SHA. Never log bot tokens.
- PR #33 is the prerequisite for #34. Merge in dependency order **only after** staging checks. Do not include Draft #32 crypto/finance changes.
- Keep `USER_TOPIC_GAME_START_ID` unset; preserve existing announcements. Do not change payment/runtime flags, wallet settings, or schema.
- Roll out **bot-only** code and the compatible Mini API messaging change as a coordinated release; do not mix with unrelated projects. Verify forum announcement smoke with **one authorized test game**, then observe worker logs and ACK state.
- On trouble: stop candidate bot, restore the pinned prior image and preflight state backup (preserve forensic copy of failed state), and recheck queued/sent events before re-enabling. Beware Telegram duplicates when send succeeded but ACK was not persisted.

**Known limits:** Telegram lacks outbound idempotency keys; crash between send and local ACK may cause a duplicate (at-least-once attempts, not exactly-once). Legacy false-positive ACKs cannot be reconstructed. Actual 300-second advance notice scheduler is still out of scope.

**Decision rule:** Advance only after staging PASS plus separate Production release authorization. No automatic deployment or live message has been performed here.
