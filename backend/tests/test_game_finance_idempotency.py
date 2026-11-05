from __future__ import annotations

import os
import unittest
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from fastapi import HTTPException
from sqlalchemy import BigInteger, create_engine, func, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.models.game import Game, GameCalledNumber, GameCard, GamePurchase
from app.models.settings import AppSetting
from app.models.user import User
from app.models.wallet import Wallet, WalletTx
from app.services.game_service import GameService
from app.services.wallet_service import WalletService


@compiles(BigInteger, "sqlite")
def _sqlite_bigint(_type, _compiler, **_kwargs):
    # SQLite requires INTEGER for automatically generated primary keys.
    return "INTEGER"


class GameFinanceIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[
                User.__table__, Wallet.__table__, WalletTx.__table__,
                Game.__table__, GamePurchase.__table__, GameCard.__table__,
                GameCalledNumber.__table__, AppSetting.__table__,
            ],
        )
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        # The real event writer uses MySQL-specific INSERT syntax; isolate it
        # so these tests exercise the actual DB wallet/game settlement paths.
        event_patch = patch("app.services.game_service.GameEventService.emit")
        event_patch.start()
        self.addCleanup(event_patch.stop)

        self.alice = User(tg_user_id=991001001, first_name="test-alice")
        self.bob = User(tg_user_id=991001002, first_name="test-bob")
        self.db.add_all([self.alice, self.bob])
        self.db.flush()
        self.db.add_all([
            Wallet(user_id=self.alice.id, balance=100000),
            Wallet(user_id=self.bob.id, balance=100000),
        ])
        self.game = Game(
            tg_group_id=-1001234567,
            tg_topic_id=6,
            admin_user_id=self.alice.id,
            card_price=5000,
            commission_rate=Decimal("0.1000"),
            game_level="LOW",
            card_layout_version=2,
            game_rule="LINE",
            status="LOBBY",
        )
        self.db.add(self.game)
        self.db.commit()

    def buy(self, *, user=None, game=None, qty=1, key="buy-1"):
        user = user or self.alice
        game = game or self.game
        result = GameService.buy_cards(
            self.db, game_id=game.id, user_id=user.id,
            qty=qty, idempotency_key=key,
        )
        self.db.commit()
        return result

    def balance(self, user=None):
        user = user or self.alice
        return int(self.db.execute(
            select(Wallet.balance).where(Wallet.user_id == user.id)
        ).scalar_one())

    def count(self, model):
        return int(self.db.execute(select(func.count()).select_from(model)).scalar_one())

    def assert_conflict(self, action):
        with self.assertRaises(HTTPException) as cm:
            action()
        self.assertEqual(cm.exception.status_code, 409)
        self.db.rollback()

    def test_exact_replay_reuses_purchase_and_debits_once(self):
        first, cards, _ = self.buy()
        replay, same_cards, _ = self.buy()
        self.assertEqual(replay.id, first.id)
        self.assertEqual([c.id for c in cards], [c.id for c in same_cards])
        self.assertEqual(self.balance(), 95000)
        self.assertEqual(self.count(WalletTx), 1)
        self.assertEqual(self.count(GamePurchase), 1)
        self.assertEqual(self.count(GameCard), 1)
        self.assertEqual(self.db.get(Game, self.game.id).sold_amount, 5000)

    def test_different_key_creates_second_valid_purchase(self):
        self.buy(key="one")
        self.buy(key="two")
        self.assertEqual(self.balance(), 90000)
        self.assertEqual(self.count(WalletTx), 2)
        self.assertEqual(self.count(GamePurchase), 2)
        self.assertEqual(self.count(GameCard), 2)

    def test_replay_with_different_qty_is_rejected(self):
        self.buy(qty=1)
        self.assert_conflict(lambda: self.buy(qty=2))
        self.assertEqual(self.balance(), 95000)
        self.assertEqual(self.count(GameCard), 1)

    def test_replay_for_other_game_is_rejected(self):
        other = Game(
            tg_group_id=-1001234567,
            tg_topic_id=8,
            admin_user_id=self.alice.id,
            card_price=5000,
            commission_rate=Decimal("0.1000"),
            game_level="MEDIUM",
            card_layout_version=2,
            game_rule="LINE",
            status="LOBBY",
        )
        self.db.add(other)
        self.db.commit()
        self.buy()
        self.assert_conflict(lambda: self.buy(game=other))
        self.assertEqual(self.balance(), 95000)
        self.assertEqual(self.count(GamePurchase), 1)
        self.assertEqual(other.sold_amount, 0)

    def test_same_total_but_changed_qty_and_unit_price_is_rejected(self):
        self.buy()
        self.game.card_price = 2500
        self.db.commit()
        # Both requests total 5000; only the purchase-specific check catches it.
        self.assert_conflict(lambda: self.buy(qty=2))
        self.assertEqual(self.balance(), 95000)
        self.assertEqual(self.count(GamePurchase), 1)

    def test_orphan_wallet_debit_cannot_fund_new_cards(self):
        WalletService.debit(
            self.db, user_id=self.alice.id, amount=5000,
            reason="BUY_CARDS", idempotency_key="orphan",
            ref_type="GAME", ref_id=self.game.id,
        )
        self.db.commit()
        self.assert_conflict(lambda: self.buy(key="orphan"))
        self.assertEqual(self.balance(), 95000)
        self.assertEqual(self.count(GamePurchase), 0)
        self.assertEqual(self.count(GameCard), 0)

    def test_replay_with_missing_cards_is_rejected(self):
        _purchase, cards, _ = self.buy()
        self.db.delete(cards[0])
        self.db.commit()
        self.assert_conflict(lambda: self.buy())
        self.assertEqual(self.balance(), 95000)
        self.assertEqual(self.count(WalletTx), 1)

    def test_wallet_credit_replay_rejects_conflicting_details(self):
        args = dict(
            user_id=self.alice.id, amount=1200, reason="ADJUST",
            idempotency_key="credit-test", ref_type="ADMIN_ADJUST", ref_id=88,
        )
        first = WalletService.credit(self.db, **args)
        self.db.commit()
        again = WalletService.credit(self.db, **args)
        self.db.commit()
        self.assertEqual(first.id, again.id)
        self.assertEqual(self.balance(), 101200)
        self.assert_conflict(lambda: WalletService.credit(self.db, **{**args, "amount": 2000}))
        self.assert_conflict(lambda: WalletService.credit(self.db, **{**args, "ref_id": 89}))
        self.assert_conflict(lambda: WalletService.credit(self.db, **{**args, "reason": "PRIZE_ROW"}))
        self.assert_conflict(lambda: WalletService.debit(self.db, **args))
        self.assertEqual(self.balance(), 101200)
        self.assertEqual(self.count(WalletTx), 1)

    def test_wallet_debit_replay_rejects_conflicting_metadata(self):
        args = dict(
            user_id=self.alice.id, amount=900, reason="WITHDRAW",
            idempotency_key="withdraw-test", ref_type="WITHDRAW", ref_id=22,
        )
        first = WalletService.debit(self.db, **args)
        self.db.commit()
        same = WalletService.debit(self.db, **args)
        self.db.commit()
        self.assertEqual(first.id, same.id)
        self.assert_conflict(lambda: WalletService.debit(
            self.db, **{**args, "ref_type": "GAME"}
        ))
        self.assertEqual(self.balance(), 99100)
        self.assertEqual(self.count(WalletTx), 1)

    def test_card_generation_failure_rolls_back_wallet_and_purchase(self):
        with patch("app.services.game_service.generate_tambola_card", side_effect=RuntimeError("card failed")):
            with self.assertRaisesRegex(RuntimeError, "card failed"):
                GameService.buy_cards(
                    self.db, game_id=self.game.id,
                    user_id=self.alice.id, qty=1,
                    idempotency_key="failed",
                )
        self.db.rollback()
        self.assertEqual(self.balance(), 100000)
        self.assertEqual(self.count(WalletTx), 0)
        self.assertEqual(self.count(GamePurchase), 0)
        self.assertEqual(self.count(GameCard), 0)

    def test_two_users_purchase_and_cancel_refunds_once(self):
        self.buy(key="a")
        self.buy(user=self.bob, key="b")
        self.assertEqual(self.balance(), 95000)
        self.assertEqual(self.balance(self.bob), 95000)
        self.game = GameService.close_lobby_game(
            self.db, game_id=self.game.id, admin_user_id=self.alice.id,
            idempotency_key="cancel-test", can_manage_any=True,
        )
        self.db.commit()
        self.assertEqual(self.balance(), 100000)
        self.assertEqual(self.balance(self.bob), 100000)
        self.assertEqual(self.game.status, "ENDED")
        GameService.close_lobby_game(
            self.db, game_id=self.game.id, admin_user_id=self.alice.id,
            idempotency_key="cancel-repeat", can_manage_any=True,
        )
        self.db.commit()
        self.assertEqual(self.count(WalletTx), 4)
        self.assertEqual(self.balance(), 100000)
        self.assertEqual(self.balance(self.bob), 100000)

    def test_line_tourna_then_final_prize_paid_once(self):
        _purchase, cards, _ = self.buy()
        self.game.status = "RUNNING"
        self.game.col_prize_amount = 1500
        self.game.row_prize_amount = 3000
        self.db.commit()
        row = [n for n in cards[0].numbers_json[:9] if n]
        for n in row[:3]:
            self.db.add(GameCalledNumber(
                game_id=self.game.id, number=n, called_by=self.alice.id,
            ))
        self.db.flush()
        GameService._check_and_payout(self.db, self.game, row[2])
        self.db.commit()
        self.assertEqual(self.balance(), 96500)
        self.assertEqual(self.game.col_paid, 1)
        GameService._check_and_payout(self.db, self.game, row[2])
        self.db.commit()
        self.assertEqual(self.balance(), 96500)
        for n in row[3:]:
            self.db.add(GameCalledNumber(
                game_id=self.game.id, number=n, called_by=self.alice.id,
            ))
        self.db.flush()
        GameService._check_and_payout(self.db, self.game, row[-1])
        self.db.commit()
        self.assertEqual(self.balance(), 99500)
        self.assertEqual(self.game.status, "ENDED")
        GameService._check_and_payout(self.db, self.game, row[-1])
        self.db.commit()
        self.assertEqual(self.balance(), 99500)
        self.assertEqual(self.count(WalletTx), 3)

    def test_full_card_does_not_pay_before_fifteen(self):
        self.game.game_rule = "FULL_CARD"
        self.db.commit()
        _purchase, cards, _ = self.buy()
        self.game.status = "RUNNING"
        self.game.col_prize_amount = 0
        self.game.row_prize_amount = 4500
        self.db.commit()
        numbers = [n for n in cards[0].numbers_json if n]
        for n in numbers[:-1]:
            self.db.add(GameCalledNumber(
                game_id=self.game.id, number=n, called_by=self.alice.id,
            ))
        self.db.flush()
        GameService._check_and_payout(self.db, self.game, numbers[-2])
        self.db.commit()
        self.assertEqual(self.balance(), 95000)
        self.db.add(GameCalledNumber(
            game_id=self.game.id, number=numbers[-1], called_by=self.alice.id,
        ))
        self.db.flush()
        GameService._check_and_payout(self.db, self.game, numbers[-1])
        self.db.commit()
        self.assertEqual(self.balance(), 99500)
        self.assertEqual(self.game.status, "ENDED")
        self.assertEqual(self.count(WalletTx), 2)


if __name__ == "__main__":
    unittest.main()
