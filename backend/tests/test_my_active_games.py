import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/15")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.game import Game, GameCalledNumber, GameCard
from app.models.settings import AppSetting
from app.models.user import User
from app.routers.mini_router import my_active_games


class MyActiveGamesTests(unittest.TestCase):
    def test_only_my_active_games_with_latest_draw_and_full_card_count(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        for model in (User, Game, GameCard, GameCalledNumber, AppSetting):
            model.__table__.create(engine)
        with Session(engine) as db:
            db.add_all([User(id=i, tg_user_id=i) for i in (1, 2)])
            db.add_all([Game(id=i, tg_group_id=1, admin_user_id=1, card_price=10, status=status)
                        for i, status in enumerate(("RUNNING", "LOBBY", "ENDED", "RUNNING"), 1)])
            db.flush()
            for i, (gid, uid) in enumerate([(1, 1)] * 201 + [(1, 2), (2, 1), (3, 1), (4, 2)], 1):
                db.add(GameCard(id=i, game_id=gid, user_id=uid, purchase_id=i,
                                numbers_json=[], fingerprint=str(i)))
            db.add_all([GameCalledNumber(id=i, game_id=1, number=n, called_by=1)
                        for i, n in ((1, 50), (2, 3))])
            db.flush()
            items = my_active_games(user_id=1, db=db)["items"]
            self.assertEqual([row["game_id"] for row in items], [1, 2])
            self.assertEqual(items[0]["card_count"], 201)
            self.assertEqual(items[0]["last_number"], 3)
            self.assertIsNone(items[1]["last_number"])
            self.assertEqual(my_active_games(user_id=3, db=db)["items"], [])
            db.add(AppSetting(k="user_restrictions", v_json={"1": {"active": True, "actions": ["ACTIVE_GAMES"]}}))
            db.flush()
            with self.assertRaises(HTTPException) as denied:
                my_active_games(user_id=1, db=db)
            self.assertEqual(denied.exception.status_code, 403)
