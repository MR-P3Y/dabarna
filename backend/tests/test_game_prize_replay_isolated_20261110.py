"""Wallet award idempotency regression with only disposable SQLite."""
import unittest
from sqlalchemy import create_engine, select, func, BigInteger
from sqlalchemy.ext.compiler import compiles
from app.models.user import User

@compiles(BigInteger, 'sqlite')
def big_integer_as_integer_for_test(element, compiler, **kw):
    return 'INTEGER'
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.core.db import Base
from app.models.wallet import Wallet, WalletTx
from app.services.wallet_service import WalletService


class AwardReplayIsolatedTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine, tables=[User.__table__, Wallet.__table__, WalletTx.__table__])
        with Session(self.engine) as db:
            db.add_all([User(id=6, tg_user_id=60006), User(id=8, tg_user_id=80008), Wallet(id=6, user_id=6, balance=100), Wallet(id=8, user_id=8, balance=100)])
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_identical_row_award_replay_leaves_balance_and_count_unchanged(self):
        key = "PRIZE_ROW:game:88:card:505"
        with Session(self.engine) as db:
            first = WalletService.credit(db, user_id=6, amount=21000,
                reason="PRIZE_ROW", idempotency_key=key, ref_type="GAME", ref_id=88)
            first_id = int(first.id)
            db.commit()
        with Session(self.engine) as db:
            replay = WalletService.credit(db, user_id=6, amount=21000,
                reason="PRIZE_ROW", idempotency_key=key, ref_type="GAME", ref_id=88)
            self.assertEqual(int(replay.id), first_id)
            db.commit()
        with Session(self.engine) as db:
            wallet = db.execute(select(Wallet).where(Wallet.user_id == 6)).scalar_one()
            self.assertEqual(int(wallet.balance), 21100)
            self.assertEqual(db.scalar(select(func.count(WalletTx.id)).where(
                WalletTx.wallet_id == wallet.id, WalletTx.idempotency_key == key)), 1)

    def test_identical_column_award_replay_leaves_balance_and_count_unchanged(self):
        key = "PRIZE_COL:game:88:card:509"
        with Session(self.engine) as db:
            original = WalletService.credit(db, user_id=8, amount=10500,
                reason="PRIZE_COL", idempotency_key=key, ref_type="GAME", ref_id=88)
            original_id = int(original.id)
            db.commit()
        with Session(self.engine) as db:
            repeat = WalletService.credit(db, user_id=8, amount=10500,
                reason="PRIZE_COL", idempotency_key=key, ref_type="GAME", ref_id=88)
            self.assertEqual(int(repeat.id), original_id)
            db.commit()
        with Session(self.engine) as db:
            wallet = db.execute(select(Wallet).where(Wallet.user_id == 8)).scalar_one()
            self.assertEqual(int(wallet.balance), 10600)

    def test_conflicting_replay_is_rejected(self):
        key = "PRIZE_ROW:game:88:card:505"
        with Session(self.engine) as db:
            WalletService.credit(db, user_id=6, amount=21000,
                reason="PRIZE_ROW", idempotency_key=key, ref_type="GAME", ref_id=88)
            db.commit()
        with Session(self.engine) as db:
            with self.assertRaises(HTTPException) as context:
                WalletService.credit(db, user_id=6, amount=21001,
                    reason="PRIZE_ROW", idempotency_key=key, ref_type="GAME", ref_id=88)
            self.assertEqual(context.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
