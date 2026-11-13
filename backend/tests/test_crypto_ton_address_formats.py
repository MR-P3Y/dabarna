import base64
import unittest

from app.services.crypto_address_change import canonical_ton_address, validate_crypto_destination, same_crypto_destination, _crc16_xmodem


class TonMainnetAddressTests(unittest.TestCase):
    def friendly(self, flag=0x11, workchain=0):
        raw=bytes([flag,workchain])+bytes.fromhex("ab"*32)
        return base64.urlsafe_b64encode(raw+_crc16_xmodem(raw).to_bytes(2,"big")).decode()

    def test_aliases_have_same_account_without_rewriting_invoice_spelling(self):
        raw="0:"+"ab"*32
        for address in (raw,self.friendly(),self.friendly(0x51)):
            self.assertEqual(canonical_ton_address(address),raw)
            self.assertTrue(same_crypto_destination("TON",address,raw))
            self.assertEqual(validate_crypto_destination("TON",address),address)

    def test_reject_testnet_flags_unsupported_tag_workchain_and_checksum(self):
        for address in (self.friendly(0x91),self.friendly(0xd1),self.friendly(0x01),self.friendly(workchain=1),self.friendly()[:-2]+"AA"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                validate_crypto_destination("TON",address)

    def test_masterchain_raw_and_standard_base64(self):
        address=self.friendly(workchain=255)
        self.assertEqual(canonical_ton_address(address),"-1:"+"ab"*32)
        self.assertEqual(canonical_ton_address(address.replace("-","+").replace("_","/")),"-1:"+"ab"*32)


if __name__=="__main__":unittest.main()
