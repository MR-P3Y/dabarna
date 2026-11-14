"""Exercise both countdown consumers and the existing Autopilot against disposable SQLite."""
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import Session

from app.core import config
from app.core.admin_guard import AdminIdentity, AdminScope
from app.core.db import Base
from app.models.game import Game, GameCalledNumber, GameCard, GamePurchase
from app.models.game_autopilot import GameAutopilotConfig
from app.models.game_event import GameEvent
from app.models.settings import AppSetting
from app.models.user import User
from app.models.wallet import Wallet, WalletTx
from app.routers.bot_router import get_bot_admin_game_report
from app.routers.mini_router import list_games
from app.services.game_autopilot_config_service import GameAutopilotConfigService
from app.services.game_autopilot_worker import GameAutopilotWorker


class CountdownIntegrationTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(engine.dispose)
        models = (User, Wallet, WalletTx, Game, GameCard, GamePurchase, GameCalledNumber, GameEvent, GameAutopilotConfig, AppSetting)
        metadata = MetaData()
        for model in models:
            model.__table__.to_metadata(metadata)
        for table in metadata.tables.values():
            for index in table.indexes:
                index.name = f"{table.name}_{index.name}"
        metadata.create_all(engine)
        self.db = Session(engine)
        self.addCleanup(self.db.close)
        self.enterContext(patch.multiple(config, GAME_AUTOPILOT_RUNTIME_ENABLED=True,
            GAME_AUTO_DRAW_ENABLED=True, USER_FORUM_CHAT_ID=-1000, GAME_AUTOPILOT_SYSTEM_USER_ID=10))
        self.enterContext(patch("app.services.game_autopilot_config_service.USER_TOPIC_GAME_LOW_ID", 7))
        self.lane = GameAutopilotConfig(level="LOW", enabled=1, start_mode="AUTO", min_unique_players=2)
        self.game = Game(id=91, status="LOBBY", execution_source="SYSTEM", card_price=1000,
            game_level="LOW", tg_group_id=-1000, tg_topic_id=7, admin_user_id=10, draw_mode="MANUAL")
        self.db.add_all([self.game, self.lane, User(id=10, tg_user_id=100)])
        self.add_card(1, 10)
        self.add_card(2, 10)
        self.db.commit()

    def add_card(self, cid, uid):
        self.db.add(GameCard(id=cid, game_id=91, user_id=uid, purchase_id=cid,
            numbers_json=[], fingerprint=str(cid)))

    def assert_timer(self, seconds):
        mini = list_games(status="LOBBY|RUNNING|ENDED", tg_group_id=-1000, limit=10, offset=0,
                          user_id=10, db=self.db)
        report = get_bot_admin_game_report(game_id=91, events_limit=20, db=self.db,
                                          admin=AdminIdentity(AdminScope.SUPER_ADMIN, "isolated"))
        self.assertIsNotNone(mini.server_time_utc)
        self.assertEqual(report.game.announce_before_seconds, int(self.lane.announce_before_seconds) if seconds is not None else None)
        for game in (mini.items[0], report.game):
            self.assertEqual(game.countdown_enabled, seconds is not None)
            self.assertEqual(game.countdown_seconds, seconds)
            if seconds is not None:
                self.assertEqual(datetime.fromisoformat(game.scheduled_start_at), self.game.scheduled_start_at)

    def test_worker_arms_and_both_surfaces_obey_real_distinct_players_and_postponements(self):
        now = datetime(2026, 11, 10, 10, 0, 0)
        def tick():
            return GameAutopilotWorker._manage_active(self.db, game=self.game, config=self.lane,
                                                      actor_user_id=10, now=now)
        self.assertEqual(tick(), "waiting_players")
        self.assert_timer(None)
        self.add_card(3, 11)
        self.assertEqual(tick(), "countdown_armed")
        self.assertEqual(self.game.scheduled_start_at, now + timedelta(seconds=30))
        self.assertEqual(tick(), "countdown_wait")
        self.assert_timer(30)
        self.lane.countdown_seconds = 80
        self.game.scheduled_start_at = now + timedelta(seconds=80)
        self.assert_timer(80)
        self.db.delete(self.db.get(GameCard, 3))
        self.db.flush()
        self.assertEqual(tick(), "waiting_players")
        self.assert_timer(None)
        self.assertEqual(self.game.status, "LOBBY")

    def test_editing_player_threshold_revokes_old_timer_on_both_surfaces(self):
        now = datetime(2026, 11, 14, 12)
        def tick(at):
            return GameAutopilotWorker._manage_active(
                self.db, game=self.game, config=self.lane, actor_user_id=10, now=at)
        def set_threshold(players):
            GameAutopilotConfigService.update(self.db, level="LOW",
                values={"min_unique_players": players}, updated_by=10, allow_commission_change=False)
            self.db.commit()
        set_threshold(1)
        self.assertEqual(tick(now), "countdown_armed")
        self.assert_timer(30)
        set_threshold(3)
        self.assert_timer(None)
        self.assertEqual(tick(now + timedelta(seconds=35)), "waiting_players")
        self.add_card(3, 11)  # Three cards, still just two people.
        self.assertEqual(tick(now + timedelta(seconds=36)), "waiting_players")
        self.add_card(4, 12)
        self.assertEqual(tick(now + timedelta(seconds=38)), "countdown_armed")
        self.assert_timer(30)
        deadline = self.game.scheduled_start_at
        self.assertEqual(deadline, now + timedelta(seconds=68))
        set_threshold(3)
        self.assertEqual(self.game.scheduled_start_at, deadline)

    def test_ineligible_and_ended_games_have_no_countdown(self):
        self.add_card(3, 11)
        self.game.scheduled_start_at = datetime(2026, 11, 10, 12, 0)
        self.game.autopilot_ready_at = self.game.scheduled_start_at - timedelta(seconds=30)
        self.assert_timer(30)
        for obj, field, value in (
            (self.game, "draw_mode", "AUTO"), (self.game, "execution_source", "ADMIN"),
            (self.game, "tg_topic_id", 88), (self.game, "status", "ENDED"),
            (self.lane, "start_mode", "MANUAL"), (self.lane, "enabled", 0),
        ):
            original = getattr(obj, field)
            with self.subTest(field=field), patch.object(config, "GAME_AUTO_DRAW_ENABLED", False):
                setattr(obj, field, value)
                self.db.flush()
                self.assert_timer(None)
            setattr(obj, field, original)
        self.db.flush()
        with patch.object(config, "GAME_AUTOPILOT_RUNTIME_ENABLED", False):
            self.assert_timer(None)
