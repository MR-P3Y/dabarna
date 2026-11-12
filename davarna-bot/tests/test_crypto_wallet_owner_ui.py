"""Owner TON/TRON menu and confirmation controls (no Telegram network)."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.routers.super_admin import super_crypto_wallet_activate_confirm, super_crypto_wallet_cancel_confirm

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
        self.assertIn("super:crypto:wallet:cancel:TRON", values)
        self.assertIn("super:crypto:wallet:edit:TRON", values)

    def test_confirm_does_not_send_unvalidated_address_in_callback_data(self):
        values = self.callback_values(super_admin_crypto_wallet_confirm_kb())
        self.assertIn("super:crypto:wallet:save", values)
        self.assertTrue(all(len(value) < 64 for value in values))

    def test_bot_has_dedicated_state_for_activation_phrase(self):
        self.assertIsNotNone(SuperAdminManageSG.waiting_for_crypto_address)
        self.assertIsNotNone(SuperAdminManageSG.waiting_for_crypto_activation_confirmation)


class OwnerCryptoConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def test_changed_proposal_cannot_reuse_confirmation(self):
        old = {"network": "TON", "address": "shown", "expected_current_address": "old", "expected_version": 1, "created_at": "first"}
        state = SimpleNamespace(get_data=AsyncMock(return_value={"wallet_activation_network": "TON", "wallet_activation_proposal": old}), clear=AsyncMock())
        api = SimpleNamespace(super_admin_crypto_wallets=AsyncMock(return_value={"runtime_enabled": False, "proposals": [{**old, "address": "replacement"}]}), super_admin_crypto_wallet_activate=AsyncMock())
        message = SimpleNamespace(text="ACTIVATE TON", answer=AsyncMock())
        await super_crypto_wallet_activate_confirm(message, state, api, is_super_admin=True)
        api.super_admin_crypto_wallet_activate.assert_not_awaited()
        state.clear.assert_awaited_once()
        self.assertIn("دوباره", message.answer.call_args.args[0])

    async def test_matching_proposal_uses_exact_reviewed_snapshot(self):
        item = {"network": "TON", "address": "shown", "expected_current_address": "old", "expected_version": 1, "created_at": "first"}
        state = SimpleNamespace(get_data=AsyncMock(return_value={"wallet_activation_network": "TON", "wallet_activation_proposal": item}), clear=AsyncMock())
        api = SimpleNamespace(super_admin_crypto_wallets=AsyncMock(return_value={"runtime_enabled": False, "proposals": [item]}), super_admin_crypto_wallet_activate=AsyncMock())
        await super_crypto_wallet_activate_confirm(SimpleNamespace(text="ACTIVATE TON", answer=AsyncMock()), state, api, is_super_admin=True)
        api.super_admin_crypto_wallet_activate.assert_awaited_once_with(network="TON", address="shown", expected_address="old", expected_version=1)

    async def test_cancellation_forwards_reviewed_version_and_requires_owner(self):
        item = {"network": "TON", "address": "shown", "created_at": "first"}
        state = SimpleNamespace(get_data=AsyncMock(return_value={"wallet_cancel_proposal": item}), clear=AsyncMock())
        api = SimpleNamespace(super_admin_crypto_wallet_cancel=AsyncMock())
        message = SimpleNamespace(text="CANCEL TON", answer=AsyncMock())
        await super_crypto_wallet_cancel_confirm(message, state, api, is_super_admin=False)
        api.super_admin_crypto_wallet_cancel.assert_not_awaited()
        await super_crypto_wallet_cancel_confirm(message, state, api, is_super_admin=True)
        api.super_admin_crypto_wallet_cancel.assert_awaited_once_with(network="TON", address="shown", created_at="first")


if __name__ == "__main__":
    unittest.main()
