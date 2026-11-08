"""Source-level admin UX checks without a browser or production data."""
from __future__ import annotations

import unittest
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static" / "mini"


class IdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key == "id":
                self.ids.append(value)


class MiniAdminUIContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.js = (STATIC / "app.js").read_text(encoding="utf-8")

    def test_unique_elements_and_bank_editor_controls(self):
        parser = IdParser()
        parser.feed(self.html)
        self.assertEqual(len(parser.ids), len(set(parser.ids)), "duplicate HTML element id")
        for component in (
            "headerRoleBadge", "headerUserStatus", "superBankCardsSection",
            "superBankCardsList", "superBankCardTitle", "superBankCardNumber",
            "superBankCardBankName", "superBankCardAccountName",
            "superBankCardIban", "superBankCardAccountNumber",
            "superBankCardActive", "superBankCardSaveBtn",
            "superBankCardDeleteBtn", "superBankCardCancelBtn",
            "superBankCardsRefreshBtn", "superBankCardsNewBtn",
            "superCryptoWalletSection", "superCryptoAddressesList",
        ):
            self.assertIn(component, parser.ids)

    def test_role_badge_separate_from_play_state(self):
        self.assertIn("function updateHeaderRoleBadge()", self.js)
        self.assertIn("updateHeaderRoleBadge();", self.js)
        self.assertIn("سوپرادمین", self.js)
        self.assertIn('headerUserStatus.textContent = "بدون بازی"', self.js)
        self.assertIn('aria-label="نقش مدیریتی"', self.html)
        self.assertIn('aria-label="وضعیت بازی"', self.html)

    def test_revoke_role_inline_without_page_reload(self):
        self.assertIn("data-role=", self.js)
        self.assertIn("async function superAdminRevokeRole(", self.js)
        self.assertIn("await refreshSuperAdminList()", self.js)
        self.assertNotIn("window.location.reload(", self.js)

    def test_bank_mutations_have_confirmation_and_version(self):
        self.assertIn("function bankCardEditPayload()", self.js)
        self.assertIn("bankDestinationsRevision", self.js)
        self.assertIn("window.confirm(operation", self.js)
        self.assertIn("refreshSuperBankDestinations()", self.js)
        self.assertIn('method: "DELETE"', self.js)
        self.assertIn('method: id ? "PUT" : "POST"', self.js)

    def test_crypto_address_ui_is_observation_only(self):
        self.assertIn("renderSuperCryptoAddresses", self.js)
        self.assertIn("settings.networks", self.js)
        self.assertIn("تغییر از این صفحه فعلاً غیرفعال", self.js)
        self.assertNotIn("/mini-api/admin/super/crypto-address-update", self.js)

    def test_no_stale_assets_and_no_misleading_all_operations_deposited(self):
        self.assertIn("finance-reject-reasons-20261108", self.html)
        self.assertIn("وضعیت نهایی نامشخص است", self.js)
        self.assertNotIn("واریزی ثبت شد. اگر رسید پیوست نشده باشد", self.js)


if __name__ == "__main__":
    unittest.main()
