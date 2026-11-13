from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from app.services.game_auto_draw_service import allowed_draw_intervals
from app.services.game_autopilot_worker import GameAutopilotWorker


class PacingTests(TestCase):
    def setUp(self):
        self.now=datetime(2026,11,13,12)
        self.db=Mock()
        self.game=SimpleNamespace(id=3,status='LOBBY',draw_mode='AUTO',scheduled_start_at=None,
            autopilot_ready_at=None,draw_mode_locked_at=None)
        self.config=SimpleNamespace(start_mode='AUTO',min_unique_players=2,countdown_seconds=45)

    def tick(self,players):
        with (patch.object(GameAutopilotWorker,'_ensure_draw_mode'),
              patch.object(GameAutopilotWorker,'_unique_players',return_value=players),
              patch('app.services.game_autopilot_worker.cfg.GAME_AUTO_DRAW_ENABLED',True),
              patch('app.services.game_autopilot_worker.GameService.start_game') as start):
            result=GameAutopilotWorker._manage_active(self.db,game=self.game,config=self.config,actor_user_id=1,now=self.now)
        return result,start

    def test_old_deadline_cannot_start_on_second_buyer(self):
        self.game.scheduled_start_at=self.now-timedelta(hours=5)
        result,start=self.tick(2)
        self.assertEqual(result,'countdown_armed')
        self.assertEqual(self.game.scheduled_start_at,self.now+timedelta(seconds=45))
        start.assert_not_called()

    def test_loss_of_readiness_cancels_and_next_readiness_gets_full_grace(self):
        self.tick(2)
        original=self.game.scheduled_start_at
        self.now+=timedelta(seconds=50)
        result,start=self.tick(1)
        self.assertEqual(result,'waiting_players')
        self.assertIsNone(self.game.scheduled_start_at)
        self.assertIsNone(self.game.autopilot_ready_at)
        start.assert_not_called()
        self.assertEqual(self.tick(2)[0],'countdown_armed')
        self.assertGreater(self.game.scheduled_start_at,original)

    def test_more_buyers_or_setting_change_does_not_move_active_deadline(self):
        self.tick(2)
        deadline=self.game.scheduled_start_at
        self.config.countdown_seconds=60
        self.now+=timedelta(seconds=10)
        self.assertEqual(self.tick(3)[0],'countdown_wait')
        self.assertEqual(self.game.scheduled_start_at,deadline)
        self.now=deadline
        self.assertEqual(self.tick(3)[0],'started')

    def test_fast_intervals_follow_stored_rule_and_layout_not_level(self):
        for rule,layout,fast in [('FULL_CARD',2,True),('LINE',2,False),('LEGACY',1,False),('FULL_CARD',1,False)]:
            for level in ('LOW','HIGH',None):
                with self.subTest(rule=rule,layout=layout,level=level):
                    choices=allowed_draw_intervals(SimpleNamespace(game_rule=rule,card_layout_version=layout,game_level=level))
                    self.assertEqual(all(x in choices for x in (2,3,4)),fast)
