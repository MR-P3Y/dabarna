from __future__ import annotations

import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.services.game_auto_draw_service import GameAutoDrawService
from app.services.game_auto_draw_worker import GameAutoDrawWorker


class _ScalarRows:
    def __init__(self, rows):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)


class GameAutoDrawServiceTests(unittest.TestCase):
    def test_remaining_sequence_excludes_called_numbers_without_duplicates(self) -> None:
        db = SimpleNamespace(execute=lambda statement: _ScalarRows([2, 9, 15]))
        sequence = GameAutoDrawService._remaining_sequence(db, game_id=7, max_number=20)

        self.assertEqual(len(sequence), 17)
        self.assertEqual(len(sequence), len(set(sequence)))
        self.assertEqual(set(sequence), set(range(1, 21)) - {2, 9, 15})

    def test_start_rejects_unsafe_interval_before_database_work(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            GameAutoDrawService.start(
                Mock(),
                game_id=1,
                admin_user_id=2,
                interval_seconds=1,
                max_number=90,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_state_reports_countdown_and_remaining_numbers(self) -> None:
        game = SimpleNamespace(id=3, status="RUNNING")
        control = SimpleNamespace(
            status="RUNNING",
            interval_seconds=8,
            sequence_json=[11, 22, 33, 44],
            cursor=2,
            next_draw_at=datetime(2026, 9, 16, 12, 0, 8),
        )
        state = GameAutoDrawService.to_dict(game, control)

        self.assertEqual(state["remaining_count"], 2)
        self.assertEqual(state["interval_seconds"], 8)
        self.assertEqual(state["next_draw_at"], "2026-09-16T12:00:08Z")


class GameAutoDrawWorkerTests(unittest.TestCase):
    @patch("app.services.game_auto_draw_worker.RedisLock")
    def test_busy_worker_lock_skips_cycle(self, lock_cls: Mock) -> None:
        lock_cls.return_value.acquire.return_value = False
        result = GameAutoDrawWorker.run_once()
        self.assertEqual(result, {"due": 0, "drawn": 0, "stopped": 0, "failed": 0})
        lock_cls.return_value.release.assert_not_called()

    @patch("app.services.game_auto_draw_worker.RedisLock")
    def test_unavailable_worker_lock_skips_cycle_safely(self, lock_cls: Mock) -> None:
        lock_cls.return_value.acquire.side_effect = RuntimeError("redis unavailable")
        result = GameAutoDrawWorker.run_once()
        self.assertEqual(result["drawn"], 0)
        lock_cls.return_value.release.assert_not_called()


if __name__ == "__main__":
    unittest.main()
