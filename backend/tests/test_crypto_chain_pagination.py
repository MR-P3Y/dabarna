"""Offline fake-provider regressions for #30 crypto scanner pagination.

Exercising the real chain parser with stubbed HTTP client. Never makes HTTP
requests, writes wallet records, or touches Production.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.services.crypto_chain_service import (
    CryptoChainService, CryptoChainUnavailable,
    TON_PAGE_LIMIT, TRON_PAGE_LIMIT,
)
from app.core import config as cfg


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Client:
    def __init__(self, fn):
        self.fn = fn
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, url, *, params, headers):
        self.calls.append(dict(params))
        return Response(self.fn(params))


def tron_tx(i: int, destination: str) -> dict:
    return {
        "transaction_id": f"tron-hash-{i}",
        "to": destination,
        "from": "test-sender",
        "token_info": {"address": cfg.CRYPTO_TRON_USDT_CONTRACT, "decimals": "6"},
        "value": "1000000",
        "block_timestamp": 1794182400000,
    }


def ton_tx(i: int) -> dict:
    return {
        "hash": f"ton-hash-{i}",
        "finality": "finalized",
        "now": 1794182400,
        "in_msg": {"value": "1000000000", "source": "test-sender"},
    }


class ChainPaginationTests(unittest.TestCase):
    def setUp(self):
        self.since = datetime(2026, 11, 8, tzinfo=timezone.utc)

    def test_tron_fingerprint_pages_and_confirmed_pages(self):
        target = "test-tron-destination"
        first = [tron_tx(i, target) for i in range(TRON_PAGE_LIMIT)]
        last = [tron_tx(TRON_PAGE_LIMIT, target)]

        def page(params):
            is_confirmed = params["only_confirmed"] == "true"
            if params.get("fingerprint") == "NEXT":
                return {"success": True, "data": last, "meta": {}}
            assert "fingerprint" not in params
            return {"success": True, "data": first,
                    "meta": {"fingerprint": "NEXT"}}

        clients = []
        def factory():
            c = Client(page)
            clients.append(c)
            return c

        with patch.object(CryptoChainService, "_client", side_effect=factory):
            result = CryptoChainService._list_tron_usdt(
                since=self.since, destination_address=target, include_pending=True,
            )
        self.assertEqual(len(result), TRON_PAGE_LIMIT + 1)
        self.assertTrue(all(t.confirmed for t in result))
        self.assertEqual(len(clients), 2)
        self.assertEqual(
            [c["fingerprint"] for c in clients[0].calls[1:]], ["NEXT"],
        )
        self.assertEqual(clients[0].calls[0]["only_confirmed"], "false")
        self.assertEqual(clients[1].calls[0]["only_confirmed"], "true")
        self.assertEqual({r.destination_address for r in result}, {target})

    def test_tron_full_page_without_cursor_fails_closed(self):
        target = "test-tron"
        client = Client(lambda params: {
            "success": True,
            "data": [tron_tx(i, target) for i in range(TRON_PAGE_LIMIT)],
            "meta": {},
        })
        with patch.object(CryptoChainService, "_client", return_value=client):
            with self.assertRaises(CryptoChainUnavailable):
                CryptoChainService._list_tron_usdt(
                    since=self.since, destination_address=target, include_pending=False,
                )

    def test_tron_repeated_fingerprint_fails_closed(self):
        target = "test-tron"
        client = Client(lambda params: {
            "success": True, "data": [tron_tx(1, target)],
            "meta": {"fingerprint": "REPEAT"},
        })
        with patch.object(CryptoChainService, "_client", return_value=client):
            with self.assertRaises(CryptoChainUnavailable):
                CryptoChainService._list_tron_usdt(
                    since=self.since, destination_address=target, include_pending=False,
                )
        self.assertEqual(len(client.calls), 2)

    def test_tron_malformed_confirmed_page_fails_whole_scan(self):
        target = "test-tron"
        def page(params):
            if params["only_confirmed"] == "true":
                return {"success": False, "data": []}
            return {"success": True, "data": [tron_tx(1, target)]}
        client = Client(page)
        with patch.object(CryptoChainService, "_client", return_value=client):
            with self.assertRaises(CryptoChainUnavailable):
                CryptoChainService._list_tron_usdt(
                    since=self.since, destination_address=target, include_pending=True,
                )

    def test_ton_offset_pagination_and_parser(self):
        target = "test-ton"
        def page(params):
            offset = int(params["offset"])
            if offset == 0:
                return {"transactions": [ton_tx(i) for i in range(TON_PAGE_LIMIT)]}
            if offset == TON_PAGE_LIMIT:
                return {"transactions": [ton_tx(TON_PAGE_LIMIT)]}
            raise AssertionError("unexpected offset")
        client = Client(page)
        with patch.object(CryptoChainService, "_client", return_value=client):
            result = CryptoChainService._list_ton(
                since=self.since, destination_address=target,
            )
        self.assertEqual(len(result), TON_PAGE_LIMIT + 1)
        self.assertEqual([p["offset"] for p in client.calls], [0, TON_PAGE_LIMIT, 0])
        self.assertEqual({t.destination_address for t in result}, {target})
        self.assertTrue(all(t.confirmed for t in result))

    def test_ton_head_shift_during_offset_scan_fails_closed(self):
        first_page = [ton_tx(i) for i in range(TON_PAGE_LIMIT)]
        reads = {"head": 0}

        def page(params):
            if int(params["offset"]) == TON_PAGE_LIMIT:
                return {"transactions": [ton_tx(TON_PAGE_LIMIT + 7)]}
            reads["head"] += 1
            if reads["head"] == 1:
                return {"transactions": first_page}
            # A new transaction appeared while requesting the later page.
            # The latest page no longer matches the snapshot we started with.
            return {"transactions": [ton_tx(9999)] + first_page[:-1]}

        client = Client(page)
        with patch.object(CryptoChainService, "_client", return_value=client):
            with self.assertRaises(CryptoChainUnavailable):
                CryptoChainService._list_ton(
                    since=self.since, destination_address="test-ton",
                )
        self.assertEqual(reads["head"], 2)
        self.assertEqual(len(client.calls), 3)

    def test_ton_repeated_page_cannot_be_reported_complete(self):
        client = Client(lambda params: {
            "transactions": [ton_tx(i) for i in range(TON_PAGE_LIMIT)]
        })
        with patch.object(CryptoChainService, "_client", return_value=client):
            with self.assertRaises(CryptoChainUnavailable):
                CryptoChainService._list_ton(
                    since=self.since, destination_address="test-ton",
                )

    def test_ton_bounded_pagination_cannot_succeed_silently(self):
        def page(params):
            offset = int(params["offset"])
            return {"transactions": [
                ton_tx(offset + i) for i in range(TON_PAGE_LIMIT)
            ]}
        client = Client(page)
        with patch.object(CryptoChainService, "_client", return_value=client), \
             patch("app.services.crypto_chain_service.MAX_CHAIN_SCAN_PAGES", 2):
            with self.assertRaises(CryptoChainUnavailable):
                CryptoChainService._list_ton(
                    since=self.since, destination_address="test-ton",
                )
        self.assertEqual(len(client.calls), 2)

    def test_ton_invalid_page_fails_closed(self):
        client = Client(lambda params: {"transactions": None})
        with patch.object(CryptoChainService, "_client", return_value=client):
            with self.assertRaises(CryptoChainUnavailable):
                CryptoChainService._list_ton(
                    since=self.since, destination_address="test-ton",
                )


if __name__ == "__main__":
    unittest.main()
