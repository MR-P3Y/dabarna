from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from app.services.crypto_worker import CryptoDepositWorker


class CryptoWorkerLockTests(unittest.TestCase):
    @patch("app.services.crypto_worker.RedisLock")
    def test_busy_lock_skips_cycle(self, lock_cls: Mock) -> None:
        lock_cls.return_value.acquire.return_value = False

        with patch.object(CryptoDepositWorker, "_process_cycle") as process_cycle:
            result = CryptoDepositWorker.run_once()

        process_cycle.assert_not_called()
        self.assertEqual(result["matched"], 0)
        lock_cls.return_value.release.assert_not_called()

    @patch("app.services.crypto_worker.RedisLock")
    def test_redis_failure_runs_cycle_without_release(self, lock_cls: Mock) -> None:
        lock_cls.return_value.acquire.side_effect = RuntimeError("redis unavailable")
        expected = {
            "transfers": 1,
            "matched": 1,
            "credited": 1,
            "review": 0,
            "expired": 0,
        }

        with patch.object(CryptoDepositWorker, "_process_cycle", return_value=expected) as process_cycle:
            result = CryptoDepositWorker.run_once()

        process_cycle.assert_called_once()
        self.assertEqual(result, expected)
        lock_cls.return_value.release.assert_not_called()


if __name__ == "__main__":
    unittest.main()
