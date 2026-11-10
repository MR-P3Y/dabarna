"""Isolated readiness diagnostics never imply completed historical reconciliation."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.crypto_rotation_readiness import assess_rotation
from app.services.crypto_late_transfer_review import HISTORICAL_STATUSES


class Count:
    def scalar_one(self):
        return 0


class Db:
    def __init__(self, observation=None):
        self.observation = observation
        self.reads = 0

    def execute(self, statement):
        self.reads += 1
        return Count()

    def get(self, model, key):
        return self.observation

    def commit(self):
        raise AssertionError("readiness must not commit")

    def flush(self):
        raise AssertionError("readiness must not flush")


class ExperimentalReadinessTests(unittest.TestCase):
    def assess(self, observation):
        with patch("app.services.crypto_rotation_readiness.rotation_enabled", return_value=True):
            return assess_rotation(Db(observation), network="TON",
                                   current_address="OLD", proposed_address="NEW")

    def test_no_scan_observation_is_not_ready(self):
        report = self.assess(None)
        self.assertFalse(report["scan_coverage"]["observation_present"])
        self.assertFalse(report["scan_coverage"]["backfill_verified"])
        self.assertFalse(report["active_change_allowed"])

    def test_even_tampered_verified_flag_cannot_enable_activation(self):
        record = SimpleNamespace(v_json={
            "checked_at": "2026-11-10", "pages_complete": True,
            "processing_complete": True, "historical_gap": False,
            "backfill_verified": True,
        })
        report = self.assess(record)
        self.assertTrue(report["scan_coverage"]["pages_complete"])
        self.assertFalse(report["scan_coverage"]["backfill_verified"])
        self.assertFalse(report["active_change_allowed"])

    def test_incomplete_scan_is_visible(self):
        record = SimpleNamespace(v_json={
            "pages_complete": False, "processing_complete": False,
            "historical_gap": True,
        })
        coverage = self.assess(record)["scan_coverage"]
        self.assertTrue(coverage["historical_gap"])
        self.assertFalse(coverage["processing_complete"])

    def test_rejected_deposits_remain_manual_review_candidates(self):
        self.assertIn("REJECTED", HISTORICAL_STATUSES)


if __name__ == "__main__":
    unittest.main()
