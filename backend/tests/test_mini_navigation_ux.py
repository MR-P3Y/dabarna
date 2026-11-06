import unittest
from pathlib import Path


MINI = Path(__file__).resolve().parents[1] / "app" / "static" / "mini"


class MiniNavigationUxTests(unittest.TestCase):
    def test_new_ui_layer_is_loaded_last(self):
        html = (MINI / "index.html").read_text(encoding="utf-8")
        self.assertTrue((MINI / "ux-v2.css").is_file())
        self.assertIn('href="./ux-v2.css?', html)
        self.assertLess(html.index('href="./styles.css?'), html.index('href="./ux-v2.css?'))

    def test_navigation_has_accessible_active_state(self):
        html = (MINI / "index.html").read_text(encoding="utf-8")
        js = (MINI / "app.js").read_text(encoding="utf-8")
        self.assertIn('aria-label="ناوبری اصلی"', html)
        self.assertIn('aria-current="page"', html)
        self.assertIn('btn.setAttribute("aria-current", "page")', js)
        self.assertIn('btn.removeAttribute("aria-current")', js)
        self.assertIn('el.setAttribute("aria-hidden", String(!isActive))', js)

    def test_notifications_and_card_entry_scroll_to_selected_game(self):
        js = (MINI / "app.js").read_text(encoding="utf-8")
        self.assertGreaterEqual(
            js.count('getEl("liveTitle")?.scrollIntoView({ behavior: "smooth", block: "start" })'),
            2,
        )


if __name__ == "__main__":
    unittest.main()
