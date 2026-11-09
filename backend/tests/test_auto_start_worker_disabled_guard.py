"""Regression: disabled AUTO worker blocks game starts without writes."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from app.services.game_service import GameService

class _DB:
    def execute(self, statement):
        return self
    def scalar_one_or_none(self):
        return self.game
    def get(self, cls, id):
        return None

class AutoStartDisabledGuardTests(unittest.TestCase):
    def test_auto_cannot_start_while_worker_disabled(self):
        db=_DB()
        db.game=SimpleNamespace(id=8642, status="LOBBY", prize_locked=0,
                                draw_mode="AUTO", admin_user_id=1)
        with patch("app.services.game_service.cfg.GAME_AUTO_DRAW_ENABLED", False):
            with self.assertRaises(HTTPException) as error:
                GameService.start_game(db,8642,1,"no-worker")
        self.assertEqual(error.exception.status_code,503)
        self.assertEqual(db.game.status,"LOBBY")
    def test_manual_start_not_affected_by_auto_gate(self):
        db=_DB()
        db.game=SimpleNamespace(id=8643, status="LOBBY", prize_locked=0,
                                draw_mode="MANUAL", admin_user_id=1,
                                draw_interval_seconds=5)
        with patch("app.services.game_service.cfg.GAME_AUTO_DRAW_ENABLED", False):
            with self.assertRaises(HTTPException) as error:
                GameService.start_game(db,8643,1,"manual")
        self.assertEqual(error.exception.status_code,400)
        self.assertIn("manual",str(error.exception.detail))
if __name__ == "__main__":
    unittest.main()
