import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/15")

from datetime import datetime
from unittest import TestCase
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.core.db import Base, get_db
from app.core.mini_security import get_mini_user_id
from app.routers import tracking_router as tracking
from app.models.game_event import GameEvent
from app.models.admin_audit import AdminAuditLog


class TrackingTests(TestCase):
    def setUp(self):
        self.engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
        metadata=MetaData()
        for table in Base.metadata.sorted_tables:
            copied=table.to_metadata(metadata)
            for index in copied.indexes:
                index.name=copied.name+"_"+index.name
        metadata.create_all(self.engine)
        self.db=Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.uid=1
        self.roles=[]
        self.patches=[
            patch.object(tracking,"_mini_role_names_for_user",side_effect=lambda db,uid:self.roles),
            patch.object(tracking,"_mini_config_roles_for_user",return_value=[]),
        ]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        app=FastAPI();app.include_router(tracking.router)
        app.dependency_overrides[get_db]=lambda:self.db
        app.dependency_overrides[get_mini_user_id]=lambda:self.uid
        self.client=TestClient(app)
        self.addCleanup(self.client.close)
        self.db.add_all([tracking.User(id=i,tg_user_id=100+i,username="user"+str(i)) for i in (1,2,3)])
        self.db.add_all([tracking.Wallet(id=i,user_id=i,balance=1000) for i in (1,2)])
        for i in range(1,27):
            self.db.add(tracking.DepositRequest(id=i,user_id=1 if i<26 else 2,amount=100,status="APPROVED",wallet_tx_id=1 if i==1 else None))
        self.db.add(tracking.WalletTx(id=1,wallet_id=1,amount=100,direction="CREDIT",reason="DEPOSIT_MANUAL",idempotency_key="test"))
        self.db.add(tracking.WithdrawRequest(id=1,user_id=2,amount=50,status="PAID",paid_tracking="BANK-123",full_name="PRIVATE",iban="PRIVATE",card_number="PRIVATE",account_number="PRIVATE"))
        self.db.add(tracking.CryptoDepositRequest(id=1,public_id="invoice-test",user_id=2,
            network="TON",asset="TON",amount_toman=100,rate_toman_per_asset=100,amount_crypto=1,
            rate_provider="fixture",destination_address="PRIVATE",tx_hash="0"*64,status="CONFIRMING",
            confirmation_count=1,required_confirmations=3,expires_at=datetime(2027,1,1)))
        self.db.add_all([tracking.Game(id=i,tg_group_id=1,admin_user_id=i,card_price=5,status="ENDED",game_rule="FULL_CARD",card_layout_version=2,display_code=f"G-261121-00{i}") for i in (1,2)])
        self.db.add(tracking.GamePurchase(id=1,game_id=1,user_id=1,qty=1,unit_price=5,total_price=5,wallet_tx_id=1))
        nums=[1,0,20,0,40,0,60,0,80,2,0,21,0,41,0,61,0,81,3,0,22,0,42,0,62,0,82]
        self.db.add(tracking.GameCard(id=1,game_id=1,user_id=1,purchase_id=1,numbers_json=nums,fingerprint="a",display_serial=1))
        self.db.add(GameEvent(id=1,game_id=1,kind="PRIZE_ROW",payload_json={"winner_card_ids":[1,9],"winner_user_ids":[1,2],"amounts_by_card":[30,40],"amount_total":70}))
        self.db.add(AdminAuditLog(id=1,actor_user_id=3,actor_scope="SUPER_ADMIN",action="deposit.approve",target_type="deposit_request",target_id=1,details_json={"reason":"verified","secret":"NEVER"}))
        self.db.commit()

    def get(self,path):
        return self.client.get("/mini-api/tracking/"+path)

    def test_ownership_pagination_and_codes(self):
        first=self.get("search?kind=deposit").json()
        self.assertEqual((first["total"],len(first["items"])),(25,20))
        second=self.get("search?kind=deposit&offset=20").json()
        self.assertEqual(len(second["items"]),5)
        self.assertFalse({v["id"] for v in first["items"]}&{v["id"] for v in second["items"]})
        r=self.get("search?q=DAV-DEP-۰۰۰۰۰۱")
        self.assertEqual(r.json()["items"][0]["id"],1)
        self.assertEqual(r.headers["cache-control"],"private, no-store")
        self.assertEqual(self.get("search?q=DAV-DEP-000026").json()["total"],0)
        self.assertEqual(self.get("deposit/26").status_code,404)
        self.assertEqual(self.get("withdraw/1").status_code,404)
        self.assertEqual(self.get("search?q=BANK-123").json()["total"],0)
        self.assertEqual(self.get("search?q="+"0"*64).json()["total"],0)
        self.assertEqual(self.get("search?owner=2").status_code,404)

    def test_finance_and_game_operator_scope(self):
        self.uid=3;self.roles=["FINANCE_ADMIN"]
        self.assertEqual(self.get("search?q=BANK-123").json()["items"][0]["kind"],"withdraw")
        self.assertEqual(self.get("search?q="+"0"*64).json()["items"][0]["kind"],"crypto")
        self.assertEqual(self.get("search?q=DAV-INVOICE-TEST").json()["items"][0]["kind"],"crypto")
        self.assertNotIn("PRIVATE",self.get("crypto/1").text)
        self.assertNotIn("PRIVATE",self.get("withdraw/1").text)
        self.assertEqual(self.get("search?kind=deposit").json()["total"],26)
        self.roles=["GAME_OPERATOR"]
        self.assertEqual(self.get("search?kind=deposit").json()["total"],0)
        self.assertEqual(self.get("card/1").status_code,404)
        self.uid=1
        self.assertEqual(self.get("game/1").status_code,200)
        self.assertEqual(self.get("game/2").status_code,404)

    def test_ambiguous_numeric_short_game_card_and_links(self):
        result=self.get("search?q=1").json()
        self.assertGreater(len(result["items"]),1)
        self.assertEqual(self.get("search?q=G-261121-001/۱").json()["items"][0]["kind"],"card")
        card=self.get("card/1").json()
        self.assertEqual(card["card"]["columns"],9)
        self.assertEqual(card["wins"][0]["amount"],30)
        self.assertNotIn("winner_user_ids",str(card))
        self.assertEqual({v["kind"] for v in card["links"]},{"game","tx","user"})
        self.assertEqual(self.get("search?q=G-261121-002").json()["total"],0)
        self.db.get(tracking.GameCard,1).numbers_json=[None]
        self.db.flush()
        malformed=self.get("card/1")
        self.assertEqual(malformed.status_code,200)
        self.assertNotIn("card",malformed.json())

    def test_authentication_required(self):
        app=FastAPI();app.include_router(tracking.router)
        app.dependency_overrides[get_db]=lambda:self.db
        with TestClient(app) as client:
            self.assertEqual(client.get("/mini-api/tracking/search").status_code,401)

    def test_audit_redaction_filters_and_old_history(self):
        self.assertEqual(self.get("deposit/1").json()["audit"]["total"],0)
        self.roles=["SUPER_ADMIN"]
        audit=self.get("deposit/1").json()["audit"]
        self.assertEqual(audit["items"][0]["reason"],"verified")
        self.assertNotIn("NEVER",str(audit))
        self.assertEqual(self.get("search?since=2026-11-22&until=2026-11-21").status_code,422)
        self.assertEqual(self.get("search?kind=deposit&status=REJECTED").json()["total"],0)
        self.assertEqual(self.get("search?q=DAV-DEP-"+"9"*40).json()["total"],0)
        self.assertEqual(self.get("search?since=2000-01-01&until=2000-01-02").json()["total"],0)
