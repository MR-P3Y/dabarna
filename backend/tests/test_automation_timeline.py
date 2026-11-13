from contextlib import ExitStack
from datetime import datetime, timedelta
from types import SimpleNamespace as Obj
from unittest import TestCase
from unittest.mock import Mock, patch

from app.models.game import GameAutoDraw
from app.models.game_autopilot import GameAutopilotConfig
from app.models.user import User
from app.services.game_automation_timeline import automation_timeline
from app.services.game_autopilot_worker import GameAutopilotWorker as Worker


class TimelineTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 13, 12)
        self.config = Obj(enabled=True, start_mode='AUTO', scheduler_mode='AUTO',
                          card_price=5000, draw_mode='AUTO', cooldown_seconds=30, repeat_interval_seconds=120)
        self.game = Obj(id=5, status='LOBBY', execution_source='SYSTEM', draw_mode='AUTO', scheduled_start_at=self.now)
        self.control = Obj(status='RUNNING', next_draw_at=self.now, interval_seconds=2)
        self.db = Mock()
        self.db.get.side_effect = lambda model, key: {User: Obj(id=1), GameAutopilotConfig:self.config, GameAutoDraw:self.control}[model]

    def timeline(self, active=True, latest=None, durations=None, runtime=True):
        with ExitStack() as stack:
            for key,value in dict(USER_FORUM_CHAT_ID=-10, GAME_AUTOPILOT_SYSTEM_USER_ID=1,
                                  GAME_AUTOPILOT_RUNTIME_ENABLED=runtime, GAME_AUTO_DRAW_ENABLED=True).items():
                stack.enter_context(patch('app.services.game_automation_timeline.cfg.'+key,value))
            stack.enter_context(patch('app.services.game_automation_timeline.AUTOPILOT_LEVELS',('LOW',)))
            stack.enter_context(patch('app.services.game_automation_timeline.GameAutopilotConfigService.topic_id_for_level',return_value=6))
            stack.enter_context(patch.object(Worker,'_active_game',return_value=self.game if active else None))
            stack.enter_context(patch.object(Worker,'_latest_ended_game',return_value=latest))
            stack.enter_context(patch.object(Worker,'countdowns_for_games',return_value=durations or {}))
            result=automation_timeline(self.db)
        self.db.add.assert_not_called()
        self.db.flush.assert_not_called()
        self.db.commit.assert_not_called()
        return result

    def test_start_only_with_backend_eligible_readiness(self):
        self.assertEqual(self.timeline()[0]['phase'],'WAITING_PLAYERS')
        result=self.timeline(durations={5:45})[0]
        self.assertEqual(result['phase'],'START')
        self.assertEqual(result['duration_seconds'],45)
        self.assertEqual(result['deadline_utc'],'2026-11-13T12:00:00+00:00')

    def test_running_auto_draw_does_not_depend_on_autopilot_or_creator(self):
        self.game.status='RUNNING'
        self.game.execution_source='ADMIN'
        self.config.enabled=False
        result=self.timeline(runtime=False)[0]
        self.assertEqual(result['phase'],'NEXT_NUMBER')
        self.assertEqual(result['duration_seconds'],2)
        self.assertEqual(set(result),{'level','phase','game_id','deadline_utc','duration_seconds'})

    def test_paused_and_manual_have_no_fake_deadline(self):
        self.game.status='RUNNING'
        self.control.status='PAUSED'
        self.assertEqual(self.timeline()[0]['phase'],'PAUSED')
        self.assertIsNone(self.timeline()[0]['deadline_utc'])
        self.game.draw_mode='MANUAL'
        self.assertEqual(self.timeline()[0]['phase'],'MANUAL_DRAW')

    def test_next_game_uses_actual_end_and_larger_delay(self):
        latest=Obj(ended_at=self.now,created_at=self.now-timedelta(days=9))
        result=self.timeline(active=False,latest=latest)[0]
        self.assertEqual(result['phase'],'NEXT_GAME')
        self.assertEqual(result['deadline_utc'],'2026-11-13T12:02:00+00:00')
        self.assertEqual(result['duration_seconds'],120)

    def test_missing_end_never_guesses_from_creation(self):
        result=self.timeline(active=False,latest=Obj(ended_at=None,created_at=self.now))[0]
        self.assertEqual(result['phase'],'MISSING_END_TIME')
        self.assertIsNone(result['deadline_utc'])

    def test_disabled_autopilot_has_no_next_game_promise(self):
        self.assertEqual(self.timeline(active=False,runtime=False),[])
        self.config.enabled=False
        self.assertEqual(self.timeline(active=False),[])
