import os, tempfile, unittest
os.environ.setdefault('TELEGRAM_BOT_TOKEN','123456789:TEST_ONLY')
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from bot.workers import notifier
from bot.services import notify_store

class PrizeTopicDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(notify_store,'_STORE_PATH',Path(self.temp.name)/'state.json');p.start();self.addCleanup(p.stop)
        self.report={'game':{'game_rule':'LINE','card_layout_version':2,'payout_state_json':{}},
          'events':[{'id':201,'kind':'PRIZE_ROW','created_at':datetime.now(timezone.utc).isoformat(),
          'payload_json':{'winner_user_ids':[10],'winner_card_ids':[1],'amounts_by_card':[30],'amount_total':30}}]}

    async def deliver(self,first=False):
        with patch.object(notifier,'_is_user_forum_game',return_value=True):
            await notifier._process_public_prize_reports(None,game_id=42,report=self.report,is_first_seen=first)

    async def test_failed_send_retries_after_restart_without_private_replay(self):
        with patch.object(notifier,'send_to_user_topic',new=AsyncMock(side_effect=[False,True])) as send:
            await self.deliver(True)
            self.assertEqual(notify_store.get_event_marker(42,'PRIZE_ROW_NOTICE_RESULTS'),0)
            notify_store.set_event_marker(42,'PRIZE_ROW',201) # old private dispatcher completed
            await self.deliver(True) # simulate restart; pending delivery wins over legacy marker
            self.assertEqual(notify_store.get_event_marker(42,'PRIZE_ROW_NOTICE_RESULTS'),201)
            await self.deliver()
            self.assertEqual(send.await_count,2)
            self.assertEqual(send.call_args.kwargs['name'],'results')
            self.assertIn('30',send.call_args.kwargs['text'])

    async def test_existing_legacy_prize_is_not_replayed_on_upgrade(self):
        notify_store.set_event_marker(42,'PRIZE_ROW',201)
        with patch.object(notifier,'send_to_user_topic',new_callable=AsyncMock) as send:
            await self.deliver(True)
            send.assert_not_awaited()

    async def test_new_event_after_old_private_marker_is_delivered(self):
        notify_store.set_event_marker(42,'PRIZE_ROW',201)
        with patch.object(notifier,'send_to_user_topic',new=AsyncMock(return_value=True)) as send:
            await self.deliver(True)
            self.report['events'][0]['id']=202
            await self.deliver()
            send.assert_awaited_once()
            self.assertEqual(notify_store.get_event_marker(42,'PRIZE_ROW_NOTICE_RESULTS'),202)
