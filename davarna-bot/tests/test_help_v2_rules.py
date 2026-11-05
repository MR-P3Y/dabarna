import os
import unittest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:TEST_ONLY")

from bot.routers.help import BASE_TOPICS


class PublicRulesTests(unittest.TestCase):
    def test_rules_explain_both_card_versions(self):
        topic = next(t for t in BASE_TOPICS if t.key == "rules")
        self.assertIn("کارت جدید ۱۵عددی", topic.body)
        self.assertIn("۳ عدد از یک ردیف", topic.body)
        self.assertIn("۵ عدد یک ردیف", topic.body)
        self.assertIn("پرکردنی", topic.body)
        self.assertIn("تورنا یا جایزه میانی ندارد", topic.body)
        self.assertIn("کارت ۲۰عددی", topic.body)
        self.assertIn("ستون ۴عددی", topic.body)


if __name__ == "__main__":
    unittest.main()
