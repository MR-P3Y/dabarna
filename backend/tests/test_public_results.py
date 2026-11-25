from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.test_tracking_center import TrackingTests
from app.routers import public_results_router as results
from app.models.game import Game
from app.models.game_event import GameEvent

class PublicResultsTests(TrackingTests):
    def setUp(self):
        super().setUp()
        self.client.app.include_router(results.router)
        self.db.get(Game,1).ended_at=datetime(2026,11,25,10)
        self.db.get(Game,2).ended_at=datetime(2026,11,25,9)
        self.db.commit()

    def test_verified_card_share_and_privacy(self):
        r=self.client.get('/mini-api/games/recent-results')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.headers['cache-control'],'private, no-store')
        first=r.json()['items'][0]
        self.assertEqual(first['winners'][0]['amount'],30)
        self.assertEqual(len(first['winners']),1)
        self.assertTrue(first['incomplete']) # second card is not owned by the recorded winner
        self.assertNotIn('user_id',r.text)
        self.assertNotIn('username',r.text)
        self.assertNotIn('tg_user_id',r.text)
        self.assertNotIn('amount_total',r.text)
        self.assertNotIn('user1',r.text)

    def test_exactly_five_completed_games_by_end_time(self):
        for i in range(3,10):
            self.db.add(Game(id=i,tg_group_id=1,admin_user_id=1,card_price=5,status='ENDED',
                game_rule='LINE',card_layout_version=2,ended_at=datetime(2026,11,25,10)+timedelta(minutes=i)))
        self.db.commit()
        rows=self.client.get('/mini-api/games/recent-results').json()['items']
        self.assertEqual([g['game_id'] for g in rows],[9,8,7,6,5])

    def test_unknown_amount_is_not_event_total(self):
        ev=self.db.get(GameEvent,1);ev.payload_json={'winner_card_ids':[1],'winner_user_ids':[1],'amount_total':9999}
        self.db.commit()
        row=self.client.get('/mini-api/games/recent-results').json()['items'][0]
        self.assertIsNone(row['winners'][0]['amount'])

    def test_full_card_never_exposes_tourna(self):
        self.db.add(GameEvent(id=2,game_id=1,kind='PRIZE_COL',payload_json={'winner_card_ids':[1],'winner_user_ids':[1],'amounts_by_card':[50]}));self.db.commit()
        row=self.client.get('/mini-api/games/recent-results').json()['items'][0]
        self.assertTrue(row['incomplete'])
        self.assertTrue(all(w['kind']=='PRIZE_ROW' for w in row['winners']))

    def test_requires_authentication(self):
        app=FastAPI();app.include_router(results.router)
        with TestClient(app) as client:self.assertEqual(client.get('/mini-api/games/recent-results').status_code,401)
