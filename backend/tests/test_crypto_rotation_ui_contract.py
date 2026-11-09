"""Read-only source contract for crypto address UI and bot entrypoint (#30).

No server, database, browser, network or payment writes.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
HTML = ROOT / "backend/app/static/mini/index.html"
JS = ROOT / "backend/app/static/mini/app.js"
ROUTER = ROOT / "backend/app/routers/mini_router.py"
KEYBOARD = ROOT / "davarna-bot/bot/keyboards/super_admin.py"


class CryptoRotationUiContractTests(unittest.TestCase):
    def test_mini_workflow_inputs_have_real_handlers(self):
        html, js = HTML.read_text(encoding="utf8"), JS.read_text(encoding="utf8")
        for target in (
            "superCryptoNetworkInput", "superCryptoProposedInput",
            "superCryptoReasonInput", "superCryptoPreviewBtn",
            "superCryptoDraftBtn", "superCryptoVersionsRefreshBtn",
            "superCryptoPrepareBtn", "superCryptoRetypeInput",
            "superCryptoConfirmBtn", "superCryptoCancelDraftBtn",
            "superCryptoDraftReview", "superCryptoVersionsList",
        ):
            self.assertIn('id="' + target + '"', html)
            self.assertIn('"' + target + '"', js)
        for action in (
            "previewSuperCryptoAddress", "draftSuperCryptoAddress",
            "prepareSuperCryptoConfirmation", "confirmSuperCryptoReview",
            "cancelSuperCryptoDraft", "refreshSuperCryptoVersions",
        ):
            self.assertIn("function " + action + "(", js)

    def test_review_api_is_owner_only_and_has_no_activate_route(self):
        router = ROUTER.read_text(encoding="utf8")
        for suffix in (
            "/crypto-destinations/preview",
            "/crypto-destinations/drafts",
            "/crypto-destinations/versions",
            "/prepare-confirmation",
            "/confirm",
        ):
            self.assertIn(suffix, router)
        self.assertNotIn('"/admin/super/crypto-destinations/activate"', router)
        self.assertNotIn('"/admin/super/crypto-destinations/apply"', router)
        self.assertIn("get_mini_super_admin_identity", router)

    def test_bot_uses_authenticated_mini_entrypoint(self):
        keyboard = KEYBOARD.read_text(encoding="utf8")
        self.assertIn("https://t.me/toofandabarna_bot/mini", keyboard)
        self.assertIn("مدیریت پیش‌نویس آدرس", keyboard)

    def test_ui_explicitly_explains_no_live_activation(self):
        html = HTML.read_text(encoding="utf8")
        js = JS.read_text(encoding="utf8")
        self.assertIn("هیچ آدرسی در این مرحله فعال نمی‌شود", html)
        self.assertIn("آدرس فعلی تغییر نکرده است", js)


if __name__ == "__main__":
    unittest.main()
