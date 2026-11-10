"""Owner TON/TRON menu and confirmation controls (no Telegram network)."""
import unittest

from bot.keyboards.super_admin import (
    super_admin_crypto_wallets_kb,
    super_admin_crypto_wallet_confirm_kb,
)
from bot.states.super_admin import SuperAdminManageSG


class OwnerCryptoWalletBotUiTests(unittest.TestCase):
    def callback_values(self, markup):
        return [button.callback_data for row in markup.inline_keyboard for button in row]

    def test_blank_network_has_first_add_action(self):
        values = self.callback_values(super_admin_crypto_wallets_kb(
            networks=[], proposals=[], runtime_enabled=False,
        ))
        self.assertIn("super:crypto:wallet:edit:TRON", values)
        self.assertIn("super:crypto:wallet:edit:TON", values)

    def test_proposal_has_separate_activation_action(self):
        values = self.callback_values(super_admin_crypto_wallets_kb(
            networks=[
                {"network": "TRON", "address": "T" + "a" * 33, "destination_version": 1},
            ],
            proposals=[{"network": "TRON", "address": "T" + "b" * 33}],
            runtime_enabled=True,
        ))
        self.assertIn("super:crypto:wallet:activate:TRON", values)
        self.assertIn("super:crypto:wallet:edit:TRON", values)

    def test_confirm_does_not_send_unvalidated_address_in_callback_data(self):
        values = self.callback_values(super_admin_crypto_wallet_confirm_kb())
        self.assertIn("super:crypto:wallet:save", values)
        self.assertTrue(all(len(value) < 64 for value in values))

    def test_bot_has_dedicated_state_for_activation_phrase(self):
        self.assertIsNotNone(SuperAdminManageSG.waiting_for_crypto_address)
        self.assertIsNotNone(SuperAdminManageSG.waiting_for_crypto_activation_confirmation)


if __name__ == "__main__":
    unittest.main()
