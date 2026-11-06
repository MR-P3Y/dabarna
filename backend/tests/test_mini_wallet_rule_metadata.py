import inspect
import unittest

from app.schemas.mini import MiniWalletTxOut
from app.routers.mini_router import my_wallet_txs


class WalletPrizeRuleMetadataTests(unittest.TestCase):
    def test_optional_rule_preserves_existing_payloads(self):
        old = MiniWalletTxOut(
            id=1,
            direction="CREDIT",
            amount=100,
            reason="PRIZE_ROW",
            ref_type="GAME",
            ref_id=82,
            created_at="2026-11-06 12:00:00",
        )
        self.assertIsNone(old.game_rule)

    def test_full_card_rule_is_exposed_without_ledger_change(self):
        new = MiniWalletTxOut(
            id=1,
            direction="CREDIT",
            amount=68000,
            reason="PRIZE_ROW",
            ref_type="GAME",
            ref_id=83,
            game_rule="FULL_CARD",
            created_at="2026-11-06 12:00:00",
        )
        self.assertEqual(new.model_dump()["game_rule"], "FULL_CARD")
        self.assertEqual(new.reason, "PRIZE_ROW")

    def test_api_looks_up_prize_rules_in_batch(self):
        source = inspect.getsource(my_wallet_txs)
        self.assertIn("select(Game.id, Game.game_rule)", source)
        self.assertIn('{"PRIZE_COL", "PRIZE_ROW"}', source)


if __name__ == "__main__":
    unittest.main()
