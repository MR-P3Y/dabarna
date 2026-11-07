import os
import unittest

os.environ.setdefault("RECEIPTS_DIR", "/tmp/receipts")

from fastapi import HTTPException
from app.services import deposit_destination_admin as cards


def sample(card="6037991234567890", active=True):
    return {
        "id": "env_1", "title": "بانک اول", "account_name": "صاحب حساب",
        "bank_name": "بانک نمونه", "card_number": card,
        "iban": "IR123456789012345678901234",
        "account_number": "123456", "is_active": active,
    }


class BankDestinationRulesTests(unittest.TestCase):
    def setUp(self):
        self.items = [sample()]

    def test_add_is_always_inactive_and_preserves_old(self):
        old_rev = cards.revision(self.items)
        new = cards.add_destination(self.items, {
            "title": "کارت جدید", "bank_name": "بانک دوم",
            "card_number": "6037999876543210",
        })
        self.assertEqual(len(new), 2)
        self.assertEqual(len(self.items), 1)
        self.assertFalse(new[-1]["is_active"])
        self.assertEqual(cards.revision(self.items), old_rev)
        self.assertNotEqual(cards.revision(new), old_rev)

    def test_duplicate_card_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            cards.add_destination(self.items, {
                "title": "دوباره",
                "card_number": "6037991234567890",
            })
        self.assertEqual(ctx.exception.status_code, 409)

    def test_undecodable_and_short_card_are_rejected(self):
        for number in ("603799123456789", "۶۰۳۷۹۹۱۲۳۴۵۶۷۸۹۰", "603799123456789X"):
            with self.subTest(number=number), self.assertRaises(HTTPException):
                cards.add_destination(self.items, {
                    "title": "نام کارت",
                    "card_number": number,
                })

    def test_iban_and_account_validation(self):
        with self.assertRaises(HTTPException):
            cards.validate_new_details({
                "title": "کارت", "card_number": "6037999876543210", "iban": "IR123",
            })
        with self.assertRaises(HTTPException):
            cards.validate_new_details({
                "title": "کارت", "card_number": "6037999876543210",
                "account_number": "1234x",
            })

    def test_bank_last_active_card_cannot_deactivate_without_disabling_service(self):
        info = {
            "title": "کارت اول", "bank_name": "بانک",
            "card_number": "6037991234567890", "is_active": False,
        }
        with self.assertRaises(HTTPException) as ctx:
            cards.update_destination(self.items, "env_1", info, bank_enabled=True)
        self.assertEqual(ctx.exception.status_code, 409)
        updated = cards.update_destination(self.items, "env_1", info, bank_enabled=False)
        self.assertFalse(updated[0]["is_active"])

    def test_delete_requires_inactive_and_not_last_card(self):
        with self.assertRaises(HTTPException):
            cards.remove_destination(self.items, "env_1")
        with self.assertRaises(HTTPException):
            cards.remove_destination([sample(active=False)], "env_1")
        collection = [sample(active=True), {**sample("6037999876543210", active=False), "id": "bank_other"}]
        updated = cards.remove_destination(collection, "bank_other")
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["id"], "env_1")

    def test_revision_detects_stale_client(self):
        original = cards.revision(self.items)
        cards.check_revision(original, self.items)
        new = cards.add_destination(self.items, {
            "title": "جدید", "card_number": "6037999876543210",
        })
        with self.assertRaises(HTTPException) as ctx:
            cards.check_revision(original, new)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_no_double_activate_or_silent_card_replacement(self):
        old = [sample(active=True), {**sample("6037999876543210", active=False), "id": "bank_2"}]
        payload = {
            "title": "دوم", "card_number": "6037999876543210",
            "bank_name": "بانک", "is_active": True,
        }
        updated = cards.update_destination(old, "bank_2", payload, bank_enabled=True)
        self.assertTrue(updated[1]["is_active"])
        self.assertEqual(updated[0]["card_number"], old[0]["card_number"])
        self.assertEqual(len(updated), 2)


if __name__ == "__main__":
    unittest.main()
