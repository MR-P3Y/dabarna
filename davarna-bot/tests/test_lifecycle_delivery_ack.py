"""Offline Telegram lifecycle ACK/restart tests. No Bot/API/network required."""
from __future__ import annotations

import ast
import importlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bot.services import lifecycle_delivery, notify_store


def event(kind="GAME_STARTED", event_id=101, minutes_ago=5):
    now = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {
        "id": event_id, "kind": kind,
        "created_at": now.isoformat(), "payload_json": {},
    }


class LifecycleDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "notif_state.json"
        p = patch.object(notify_store, "_STORE_PATH", self.path)
        p.start()
        self.addCleanup(p.stop)

    def marker(self, key):
        return notify_store.get_event_marker(42, key)

    def pending(self, key):
        return notify_store.get_meta_marker(f"lifecycle_pending:42:{key}", "")

    async def deliver(self, key, send, *, sample=None, first=False, legacy=None, already=False):
        return await lifecycle_delivery.deliver_lifecycle_event(
            game_id=42, event_key=key,
            event=sample or event(),
            is_first_seen=first, legacy_event_key=legacy,
            send=send, already_delivered=already,
        )

    async def test_failure_retains_pending_and_retries_until_success(self):
        key = "GAME_STARTED_NOTICE_USER"
        sender = AsyncMock(side_effect=[False, True])
        self.assertFalse(await self.deliver(key, sender))
        self.assertEqual(self.marker(key), 0)
        self.assertEqual(self.pending(key), "101")
        self.assertTrue(await self.deliver(key, sender))
        self.assertEqual(self.marker(key), 101)
        self.assertEqual(self.pending(key), "")
        self.assertTrue(await self.deliver(key, sender))
        self.assertEqual(sender.await_count, 2)

    async def test_restart_retries_pending_even_after_recovery_window(self):
        key = "GAME_ENDED_NOTICE_USER"
        old_event = event("GAME_ENDED", 102, minutes_ago=500)
        self.assertFalse(await self.deliver(key, AsyncMock(return_value=False),
                                            sample=old_event, first=False))
        self.assertTrue(self.path.is_file())
        importlib.reload(lifecycle_delivery)
        sender = AsyncMock(return_value=True)
        self.assertTrue(await self.deliver(key, sender, sample=old_event, first=True))
        self.assertEqual(sender.await_count, 1)
        self.assertEqual(self.marker(key), 102)

    async def test_user_and_admin_destinations_do_not_replay_each_other(self):
        admin = "GAME_STARTED_NOTICE_ADMIN"
        user = "GAME_STARTED_NOTICE_USER"
        self.assertFalse(await self.deliver(admin, AsyncMock(return_value=False)))
        sent_user = AsyncMock(return_value=True)
        self.assertTrue(await self.deliver(user, sent_user))
        self.assertEqual(self.marker(admin), 0)
        self.assertEqual(self.marker(user), 101)
        self.assertTrue(await self.deliver(admin, AsyncMock(return_value=True)))
        self.assertEqual(self.marker(admin), 101)
        self.assertTrue(await self.deliver(user, sent_user))
        sent_user.assert_awaited_once()

    async def test_exception_does_not_ack_or_erase_pending(self):
        key = "GAME_CREATED_NOTICE_USER"
        with patch.object(lifecycle_delivery.logger, "exception"):
            self.assertFalse(await self.deliver(
                key, AsyncMock(side_effect=OSError("telegram timeout")),
            ))
        self.assertEqual(self.marker(key), 0)
        self.assertEqual(self.pending(key), "101")

    async def test_warm_start_recent_event_is_delivered(self):
        key = "GAME_STARTED_NOTICE_USER"
        sender = AsyncMock(return_value=True)
        self.assertTrue(await self.deliver(key, sender, first=True))
        sender.assert_awaited_once()

    async def test_stale_untracked_event_skips_initial_backfill(self):
        key = "GAME_STARTED_NOTICE_USER"
        sender = AsyncMock(return_value=True)
        self.assertTrue(await self.deliver(
            key, sender, sample=event(minutes_ago=300), first=True,
        ))
        sender.assert_not_awaited()
        self.assertEqual(self.marker(key), 101)

    async def test_existing_legacy_ack_prevents_old_message_replay(self):
        notify_store.set_event_marker(42, "GAME_STARTED_NOTICE", 101)
        sender = AsyncMock(return_value=True)
        self.assertTrue(await self.deliver(
            "GAME_STARTED_NOTICE_USER", sender,
            first=True, legacy="GAME_STARTED_NOTICE",
        ))
        sender.assert_not_awaited()
        self.assertEqual(self.marker("GAME_STARTED_NOTICE_USER"), 101)

    async def test_future_event_after_legacy_ack_can_be_sent(self):
        notify_store.set_event_marker(42, "GAME_STARTED_NOTICE", 99)
        sender = AsyncMock(return_value=True)
        self.assertTrue(await self.deliver(
            "GAME_STARTED_NOTICE_ADMIN", sender,
            sample=event(event_id=101), first=True,
            legacy="GAME_STARTED_NOTICE",
        ))
        sender.assert_awaited_once()

    async def test_mini_created_ack_skips_duplicate(self):
        key = "GAME_CREATED_NOTICE_USER"
        sender = AsyncMock(return_value=True)
        self.assertTrue(await self.deliver(key, sender, already=True))
        sender.assert_not_awaited()
        self.assertEqual(self.marker(key), 101)

    async def test_failed_pending_storage_never_sends(self):
        sender = AsyncMock(return_value=True)
        with patch.object(lifecycle_delivery, "set_meta_marker",
                          side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await self.deliver("GAME_STARTED_NOTICE_USER", sender)
        sender.assert_not_awaited()

    async def test_crash_after_telegram_ack_before_persist_can_duplicate(self):
        key = "GAME_STARTED_NOTICE_USER"
        sender = AsyncMock(return_value=True)
        with patch.object(lifecycle_delivery, "set_event_marker",
                          side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await self.deliver(key, sender)
        self.assertEqual(self.pending(key), "101")
        self.assertEqual(self.marker(key), 0)
        self.assertTrue(await self.deliver(key, sender))
        self.assertEqual(sender.await_count, 2)
        self.assertEqual(self.marker(key), 101)

    async def test_corrupted_state_is_not_reset_or_overwritten(self):
        key = "GAME_STARTED_NOTICE_USER"
        self.path.write_text("{invalid-json", encoding="utf-8")
        sender = AsyncMock(return_value=True)
        with self.assertRaises(RuntimeError):
            await self.deliver(key, sender)
        sender.assert_not_awaited()
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{invalid-json")

    async def test_atomic_replace_failure_preserves_old_ack_file(self):
        import json
        notify_store.set_event_marker(42, "GAME_CREATED_NOTICE_USER", 33)
        before = self.path.read_text(encoding="utf-8")
        with patch.object(notify_store.os, "replace", side_effect=OSError("storage failure")):
            with self.assertRaises(OSError):
                notify_store.set_event_marker(42, "GAME_CREATED_NOTICE_USER", 34)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        self.assertEqual(json.loads(before)["events"]["42"]["GAME_CREATED_NOTICE_USER"], 33)

    async def test_state_json_is_parseable_after_multiple_updates(self):
        import json
        for i in range(10):
            notify_store.set_event_marker(42, "SYNTHETIC", i)
        obj = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(obj["events"]["42"]["SYNTHETIC"], 9)
        self.assertFalse(list(self.path.parent.glob("*.tmp")))


class RealNotifierWiringTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        p = patch.object(notify_store, "_STORE_PATH",
                         Path(self.tempdir.name) / "notif_state.json")
        p.start()
        self.addCleanup(p.stop)

    async def test_actual_lifecycle_processor_separates_targets_and_retries(self):
        # Compile just the function, not Aiogram-dependent notifier imports.
        source = Path(__file__).resolve().parents[1] / "bot/workers/notifier.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        f = next(
            x for x in tree.body
            if isinstance(x, ast.AsyncFunctionDef)
            and x.name == "_process_game_lifecycle_reports"
        )
        module = ast.Module(body=[
            ast.ImportFrom(module="__future__",
                           names=[ast.alias(name="annotations")], level=0),
            f,
        ], type_ignores=[])
        import copy
        from types import SimpleNamespace
        report = {"events": [event("GAME_CREATED", 10),
                             event("GAME_STARTED", 11),
                             event("GAME_ENDED", 12)]}
        send_admin_start = AsyncMock(side_effect=[False, True])
        send_admin_end = AsyncMock(return_value=True)
        send_user_start = AsyncMock(return_value=True)
        send_user_end = AsyncMock(return_value=True)
        send_user_created = AsyncMock(return_value=True)

        def latest(events, kind):
            return next((e for e in events if e["kind"] == kind), None)

        namespace = {
            "deliver_lifecycle_event": lifecycle_delivery.deliver_lifecycle_event,
            "_latest_event": latest,
            "_event_payload": lambda e: (e or {}).get("payload_json") or {},
            "_send_game_started_report": send_admin_start,
            "_send_game_ended_report": send_admin_end,
            "_send_user_game_started_notice": send_user_start,
            "_send_user_game_ended_notice": send_user_end,
            "_send_user_game_created_notice": send_user_created,
        }
        exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
        processor = namespace["_process_game_lifecycle_reports"]
        await processor(
            bot=None, game_id=42, report=report,
            runtime_started_ts=0, is_first_seen=True,
        )
        self.assertEqual(send_admin_start.await_count, 1)
        self.assertEqual(send_user_start.await_count, 1)
        self.assertEqual(send_admin_end.await_count, 1)
        self.assertEqual(send_user_end.await_count, 1)
        self.assertEqual(send_user_created.await_count, 1)
        self.assertEqual(notify_store.get_event_marker(42, "GAME_STARTED_NOTICE_ADMIN"), 0)
        self.assertEqual(notify_store.get_event_marker(42, "GAME_STARTED_NOTICE_USER"), 11)

        # Simulate a process restart and the next scan. Only the failed
        # admin-start delivery is replayed; the four successful sends stay ACKed.
        await processor(
            bot=None, game_id=42, report=report,
            runtime_started_ts=9999999999, is_first_seen=True,
        )
        self.assertEqual(send_admin_start.await_count, 2)
        for mock in (send_admin_end, send_user_start, send_user_end,
                     send_user_created):
            mock.assert_awaited_once()
        self.assertEqual(notify_store.get_event_marker(42, "GAME_STARTED_NOTICE_ADMIN"), 11)


if __name__ == "__main__":
    unittest.main()
