import ast
from pathlib import Path
import unittest

from app.schemas.mini import MiniWalletTxOut


ROUTER_PATH = Path(__file__).resolve().parents[1] / "app" / "routers" / "mini_router.py"


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
        # Parse endpoint source without importing the router. Importing it loads
        # production-oriented config and requires DATABASE_URL and REDIS_URL.
        source = ROUTER_PATH.read_text(encoding="utf-8")
        module = ast.parse(source, filename=str(ROUTER_PATH))
        endpoint = next(
            (
                node for node in module.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "my_wallet_txs"
            ),
            None,
        )
        self.assertIsNotNone(endpoint, "Wallet transaction endpoint is missing")
        endpoint_source = ast.get_source_segment(source, endpoint)
        self.assertIn("select(Game.id, Game.game_rule)", endpoint_source)
        self.assertIn('{"PRIZE_COL", "PRIZE_ROW"}', endpoint_source)
        self.assertIn("game_rule=game_rules.get(", endpoint_source)


if __name__ == "__main__":
    unittest.main()
