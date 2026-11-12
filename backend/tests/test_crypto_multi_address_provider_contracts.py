"""Mocked TronGrid and TON Center address-rotation API contracts.

All HTTP requests use httpx.MockTransport; no real providers or DB touched.
"""
from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import patch

import httpx

from app.services.crypto_chain_service import CryptoChainService


def _response(payload):
    return httpx.Response(200, json=payload)


class MultiAddressProviderContracts(TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 10, tzinfo=timezone.utc).replace(tzinfo=None)

    def test_tron_old_new_addresses_are_queried_separately(self):
        visited = []
        def handler(request):
            visited.append(str(request.url))
            address = str(request.url).split("/v1/accounts/")[1].split("/")[0]
            if "only_confirmed=true" in str(request.url):
                return _response({"success": True, "data": [{"transaction_id": "tx-" + address}]})
            return _response({
                "success": True,
                "data": [
                    {"transaction_id": "tx-" + address,
                     "to": address, "from": "SENDER",
                     "value": "1250000", "block_timestamp": 1794312000000,
                     "token_info": {"address": "TOKEN", "decimals": "6"}},
                    {"transaction_id": "wrong-" + address,
                     "to": "OTHER", "from": "SENDER",
                     "value": "1250000", "block_timestamp": 1794312000000,
                     "token_info": {"address": "TOKEN", "decimals": "6"}},
                ],
            })
        with (
            patch.object(CryptoChainService, "_client", side_effect=lambda: httpx.Client(transport=httpx.MockTransport(handler))),
            patch("app.services.crypto_chain_service.cfg.CRYPTO_TRON_USDT_CONTRACT", "TOKEN"),
            patch("app.services.crypto_chain_service.cfg.CRYPTO_TRONGRID_BASE_URL", "https://mock.tron.local"),
            patch("app.services.crypto_chain_service.cfg.TRONGRID_API_KEY", ""),
        ):
            old = CryptoChainService.list_incoming(network="TRON", since=self.now, destination_address="OLD")
            new = CryptoChainService.list_incoming(network="TRON", since=self.now, destination_address="NEW")
        self.assertEqual([x.destination_address for x in old], ["OLD"])
        self.assertEqual([x.destination_address for x in new], ["NEW"])
        self.assertEqual(old[0].amount, new[0].amount)
        self.assertTrue(old[0].confirmed)
        self.assertEqual(len(visited), 4)
        self.assertTrue(any("/OLD/transactions/trc20" in url for url in visited))
        self.assertTrue(any("/NEW/transactions/trc20" in url for url in visited))

    def test_ton_old_new_accounts_are_queried_separately(self):
        visited = []
        def handler(request):
            address = request.url.params.get("account")
            visited.append(address)
            return _response({
                "transactions": [{
                    "hash": "tx-" + address, "now": 1794312000,
                    "finality": "finalized",
                    "description": {"aborted": False},
                    "in_msg": {
                        "source": "SENDER", "value": "2100000000",
                        "message_content": {"decoded": {"comment": "DAV-ROTATE"}},
                    },
                }],
            })
        with (
            patch.object(CryptoChainService, "_client", side_effect=lambda: httpx.Client(transport=httpx.MockTransport(handler))),
            patch("app.services.crypto_chain_service.cfg.CRYPTO_TONCENTER_BASE_URL", "https://mock.ton.local"),
            patch("app.services.crypto_chain_service.cfg.TONCENTER_API_KEY", ""),
        ):
            old = CryptoChainService.list_incoming(network="TON", since=self.now, destination_address="TON_OLD")
            new = CryptoChainService.list_incoming(network="TON", since=self.now, destination_address="TON_NEW")
        self.assertEqual(visited, ["TON_OLD", "TON_NEW"])
        self.assertEqual(old[0].destination_address, "TON_OLD")
        self.assertEqual(new[0].destination_address, "TON_NEW")
        self.assertEqual(new[0].memo, "DAV-ROTATE")
        self.assertTrue(new[0].confirmed)

    def test_provider_failure_raises_not_empty_success(self):
        def handler(request):
            return httpx.Response(503, json={"error": "upstream down"})
        with (
            patch.object(CryptoChainService, "_client", side_effect=lambda: httpx.Client(transport=httpx.MockTransport(handler))),
            patch("app.services.crypto_chain_service.cfg.CRYPTO_TONCENTER_BASE_URL", "https://mock.ton.local"),
        ):
            with self.assertRaises(httpx.HTTPStatusError):
                CryptoChainService.list_incoming(network="TON", since=self.now, destination_address="TON_NEW")


if __name__ == "__main__":
    import unittest
    unittest.main()
