import ast
from pathlib import Path
import unittest


ROUTER = Path(__file__).resolve().parents[1] / "app" / "routers" / "bot_router.py"


class BotWalletRuleMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ROUTER.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(ROUTER))

    def test_wallet_output_has_optional_game_rule(self):
        model = next(
            node for node in self.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "WalletTxOut"
        )
        code = ast.get_source_segment(self.source, model)
        self.assertIn("game_rule: str | None = None", code)
        self.assertIn("idempotency_key: str | None = None", code)

    def test_wallet_endpoint_queries_rules_once_per_page(self):
        endpoint = next(
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "get_wallet"
        )
        code = ast.get_source_segment(self.source, endpoint)
        self.assertIn('{"PRIZE_COL", "PRIZE_ROW"}', code)
        self.assertIn('str(tx.ref_type or "").upper() == "GAME"', code)
        self.assertIn("select(Game.id, Game.game_rule, Game.card_layout_version)", code)
        self.assertIn("game_rule=game_rules.get(", code)
        self.assertIn("idempotency_key=str(tx.idempotency_key)", code)


if __name__ == "__main__":
    unittest.main()
