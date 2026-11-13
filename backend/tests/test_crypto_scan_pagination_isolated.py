"""Provider pagination safety tests: all mocked, no network or production database."""
from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import patch

import httpx

from app.services.crypto_chain_service import CryptoChainService, CryptoChainUnavailable


class ScanPaginationTests(TestCase):
    def setUp(self):
        self.since = datetime(2026, 11, 10, tzinfo=timezone.utc).replace(tzinfo=None)

    def test_tron_fingerprint_second_page_is_processed(self):
        calls = []
        def handler(request):
            confirmed = request.url.params.get("only_confirmed") == "true"
            cursor = request.url.params.get("fingerprint")
            calls.append((confirmed, cursor))
            if confirmed:
                return httpx.Response(200, json={"success": True, "data": [
                    {"transaction_id": "first"}, {"transaction_id": "second"}]})
            if cursor == "NEXT":
                ids = ["second"]
                meta = {}
            else:
                ids = ["first"]
                meta = {"fingerprint": "NEXT"}
            return httpx.Response(200, json={"success": True, "meta": meta, "data": [
                {"transaction_id": tx, "to": "OLD", "from": "SENDER", "value": "1000000",
                 "block_timestamp": 1794312000000,
                 "token_info": {"address": "TOKEN", "decimals": 6}} for tx in ids]})
        with (
            patch.object(CryptoChainService, "_client", side_effect=lambda: httpx.Client(transport=httpx.MockTransport(handler))),
            patch("app.services.crypto_chain_service.cfg.CRYPTO_TRON_USDT_CONTRACT", "TOKEN"),
            patch("app.services.crypto_chain_service.cfg.CRYPTO_TRONGRID_BASE_URL", "https://mock.tron.local"),
            patch("app.services.crypto_chain_service.cfg.TRONGRID_API_KEY", ""),
        ):
            transfers = CryptoChainService.list_incoming(network="TRON", since=self.since, destination_address="OLD")
        self.assertEqual([t.tx_hash for t in transfers], ["first", "second"])
        self.assertTrue(all(t.confirmed for t in transfers))
        self.assertIn((False, "NEXT"), calls)

    def test_tron_repeated_cursor_fails_closed(self):
        def handler(request):
            return httpx.Response(200, json={
                "success": True, "meta": {"fingerprint": "LOOP"}, "data": []})
        with (
            patch.object(CryptoChainService, "_client", side_effect=lambda: httpx.Client(transport=httpx.MockTransport(handler))),
            patch("app.services.crypto_chain_service.cfg.CRYPTO_TRONGRID_BASE_URL", "https://mock.tron.local"),
            patch("app.services.crypto_chain_service.cfg.TRONGRID_API_KEY", ""),
        ):
            with self.assertRaises(CryptoChainUnavailable):
                CryptoChainService.list_incoming(network="TRON", since=self.since, destination_address="OLD", include_pending=False)

    def test_ton_offset_second_page_and_total(self):
        offsets = []
        def handler(request):
            offset = int(request.url.params.get("offset", "0"))
            offsets.append(offset)
            count = 100 if offset == 0 else 1
            return httpx.Response(200, json={"transactions": [
                {"hash": f"tx-{offset + i}", "now": 1794312000,
                 "finality": "finalized", "description": {"aborted": False},
                 "in_msg": {"source": "SENDER", "value": "1000000000"}}
                for i in range(count)]})
        with (
            patch.object(CryptoChainService, "_client", side_effect=lambda: httpx.Client(transport=httpx.MockTransport(handler))),
            patch("app.services.crypto_chain_service.cfg.CRYPTO_TONCENTER_BASE_URL", "https://mock.ton.local"),
            patch("app.services.crypto_chain_service.cfg.TONCENTER_API_KEY", ""),
        ):
            transfers = CryptoChainService.list_incoming(network="TON", since=self.since, destination_address="OLD")
        self.assertEqual(offsets, [0, 100])
        self.assertEqual(len(transfers), 101)
        self.assertEqual(transfers[-1].tx_hash, "tx-100")

    def test_ton_provider_failure_on_later_page_is_not_partial_success(self):
        def handler(request):
            if request.url.params.get("offset") == "100":
                return httpx.Response(503, json={"error": "unavailable"})
            return httpx.Response(200, json={"transactions": [{} for _ in range(100)]})
        with (
            patch.object(CryptoChainService, "_client", side_effect=lambda: httpx.Client(transport=httpx.MockTransport(handler))),
            patch("app.services.crypto_chain_service.cfg.CRYPTO_TONCENTER_BASE_URL", "https://mock.ton.local"),
        ):
            with self.assertRaises(httpx.HTTPStatusError):
                CryptoChainService.list_incoming(network="TON", since=self.since, destination_address="OLD")


if __name__ == "__main__":
    import unittest
    unittest.main()
