"""Read-only history reconciliation and strict provider contracts; no network."""
import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import httpx

from app.services.crypto_address_change import _crc16_xmodem
from app.services.crypto_chain_service import CryptoChainService, CryptoChainUnavailable, ChainTransfer
from app.services.crypto_history_review import review_destination_history

TON = '0:' + 'ab' * 32


class HistoryReviewTests(TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        self.invoice = SimpleNamespace(id=1, network='TON', destination_address=TON,
            user_id=7, amount_toman=100,
            status='EXPIRED', created_at=self.now-timedelta(days=7), expires_at=self.now-timedelta(days=6),
            tx_hash=None, wallet_tx_id=None, paid_amount_crypto=None, asset='TON', memo='DAV-1')
        self.transfer = ChainTransfer(network='TON', asset='TON', tx_hash='tx1', amount=Decimal('1'),
            sender_address=None, destination_address=TON, occurred_at=self.now-timedelta(days=6, hours=1),
            memo='DAV-1')

    def review(self, transfers=(), rows=None, error=None):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [self.invoice] if rows is None else rows
        from app.models.wallet import WalletTx
        db.get.side_effect = lambda model, key: SimpleNamespace(wallet_id=3, direction='CREDIT',
            reason='DEPOSIT_CRYPTO', ref_type='CRYPTO_DEPOSIT', ref_id=1, amount=100) if model is WalletTx else SimpleNamespace(user_id=7)
        with patch.object(CryptoChainService, 'list_incoming', return_value=list(transfers), side_effect=error) as provider:
            result = review_destination_history(db, network='TON', address=TON)
        for name in ('add', 'delete', 'flush', 'commit', 'rollback'):
            getattr(db, name).assert_not_called()
        self.assertFalse(result['activation_allowed'])
        self.assertFalse(result['writes_performed'])
        return result, provider

    def test_expired_history_with_empty_scan_is_reviewed_without_granting_activation(self):
        result, provider = self.review()
        self.assertEqual(result['status'], 'REVIEWED_NO_DISCREPANCY')
        self.assertEqual(result['reconciled_invoices'], 1)
        self.assertTrue(provider.call_args.kwargs['strict'])
        self.assertLess(provider.call_args.kwargs['since'], self.invoice.created_at)
        self.assertIsNotNone(provider.call_args.kwargs['until'])

    def test_late_payment_cannot_be_ignored_or_credited(self):
        result, _ = self.review([self.transfer])
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['unassigned_transfers'], 1)

    def test_credited_invoice_requires_matching_chain_amount_memo_and_wallet_reference(self):
        self.invoice.status = 'CREDITED'
        self.invoice.tx_hash = 'tx1'
        self.invoice.wallet_tx_id = 1
        self.invoice.paid_amount_crypto = Decimal('1')
        result, _ = self.review([self.transfer])
        self.assertEqual(result['status'], 'REVIEWED_NO_DISCREPANCY')
        for field, value in [('paid_amount_crypto', Decimal('2')), ('memo', 'different'), ('wallet_tx_id', None)]:
            old = getattr(self.invoice, field)
            setattr(self.invoice, field, value)
            with self.subTest(field=field):
                result, _ = self.review([self.transfer])
                self.assertIn('CREDITED_INVOICE_MISMATCH', result['blockers'])
            setattr(self.invoice, field, old)
        result, _ = self.review([])
        self.assertIn('CREDITED_INVOICE_MISMATCH', result['blockers'])

    def test_provider_failure_is_redacted_and_not_success(self):
        result, _ = self.review(error=RuntimeError('SECRET-in-provider-url'))
        self.assertFalse(result['provider_scan_complete'])
        self.assertIn('PROVIDER_SCAN_FAILED', result['blockers'])
        self.assertNotIn('SECRET', str(result))

    def test_duplicate_and_pending_transfers_block(self):
        result, _ = self.review([self.transfer, self.transfer])
        self.assertIn('DUPLICATE_PROVIDER_TRANSACTION', result['blockers'])
        pending = ChainTransfer(**{**self.transfer.__dict__, 'confirmed': False})
        result, _ = self.review([pending])
        self.assertEqual(result['unconfirmed_transfers'], 1)

    def test_ton_alias_is_included_without_rewriting_invoice(self):
        raw = bytes([0x51, 0]) + bytes.fromhex('ab' * 32)
        friendly = base64.urlsafe_b64encode(raw + _crc16_xmodem(raw).to_bytes(2, 'big')).decode()
        self.invoice.destination_address = friendly
        result, _ = self.review()
        self.assertEqual(result['historical_invoices'], 1)
        self.assertEqual(self.invoice.destination_address, friendly)

    def test_invalid_alias_fails_closed(self):
        self.invoice.destination_address = 'corrupt'
        result, _ = self.review()
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('INVALID_HISTORICAL_DESTINATION', result['blockers'])

    def test_open_and_recent_closed_invoices_block(self):
        self.invoice.status = 'WAITING_PAYMENT'
        result, _ = self.review()
        self.assertIn('UNRESOLVED_INVOICE', result['blockers'])
        self.invoice.status = 'CANCELLED'
        self.invoice.expires_at = self.now + timedelta(minutes=10)
        result, _ = self.review()
        self.assertIn('PAYMENT_GRACE_ACTIVE', result['blockers'])

    def test_no_history_does_not_call_provider(self):
        result, provider = self.review(rows=[])
        provider.assert_not_called()
        self.assertEqual(result['status'], 'NO_HISTORY')


class StrictHistoryProviderTests(TestCase):
    def setUp(self):
        self.since = datetime(2026, 11, 1)
        self.until = datetime(2026, 11, 2)
        self.timestamp = int(self.since.replace(tzinfo=timezone.utc).timestamp()) + 100

    def scan(self, network, payload, calls):
        def handler(request):
            calls.append(dict(request.url.params))
            return httpx.Response(200, json=payload)
        with patch.object(CryptoChainService, '_client', side_effect=lambda: httpx.Client(transport=httpx.MockTransport(handler))):
            return CryptoChainService.list_incoming(network=network, destination_address=TON if network=='TON' else 'TRON',
                since=self.since, until=self.until, strict=True, include_pending=False)

    def ton_row(self):
        return {'account':TON, 'hash':'tx1', 'now':self.timestamp, 'finality':'finalized',
                'description':{'aborted':False}, 'in_msg':{'destination':TON, 'value':'1000000000'}}

    def test_ton_uses_fixed_utc_bounds_and_verifies_actual_destination(self):
        calls=[]
        transfers=self.scan('TON', {'transactions':[self.ton_row()]}, calls)
        self.assertEqual(len(transfers), 1)
        self.assertEqual(int(calls[0]['start_utime']), self.timestamp-100)
        self.assertEqual(int(calls[0]['end_utime']), int(self.until.replace(tzinfo=timezone.utc).timestamp()))
        for row in [None, {}, {**self.ton_row(), 'finality':'unknown'},
                    {**self.ton_row(), 'in_msg':{'destination':'0:'+'cd'*32,'value':'100'}}]:
            with self.subTest(row=row), self.assertRaises(CryptoChainUnavailable):
                self.scan('TON', {'transactions':[row]}, [])

    def test_ton_nonfinite_and_outside_interval_are_rejected(self):
        for value in ('NaN', 'Infinity', '-1'):
            row=self.ton_row(); row['in_msg']['value']=value
            with self.subTest(value=value), self.assertRaises(CryptoChainUnavailable):
                self.scan('TON', {'transactions':[row]}, [])
        row=self.ton_row(); row['now']=self.timestamp-200
        with self.assertRaises(CryptoChainUnavailable):
            self.scan('TON', {'transactions':[row]}, [])

    def test_tron_fixed_bounds_and_malformed_rows(self):
        from app.core import config as cfg
        row={'transaction_id':'tx1','to':'TRON','value':'1000000','block_timestamp':self.timestamp*1000,
             'token_info':{'address':cfg.CRYPTO_TRON_USDT_CONTRACT,'decimals':6}}
        calls=[]
        self.assertEqual(len(self.scan('TRON', {'success':True,'data':[row]}, calls)),1)
        self.assertIn('max_timestamp',calls[0])
        for invalid in [None, {}, {**row,'value':'NaN'}, {**row,'to':'WRONG'},
                        {**row,'token_info':{**row['token_info'],'decimals':None}}]:
            with self.subTest(row=invalid), self.assertRaises(CryptoChainUnavailable):
                self.scan('TRON', {'success':True,'data':[invalid]}, [])
