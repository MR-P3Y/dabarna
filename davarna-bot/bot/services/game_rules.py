"""Single source of truth for user-facing game rules in the Telegram bot.

Always use the rule stored on the *game*. A forum topic name is not proof of
a game's rule; historical 4x5 cards remain LEGACY.
"""
from __future__ import annotations

from collections.abc import Mapping


def rule_kind(game: Mapping | None) -> str:
    game = game or {}
    rule = str(game.get("game_rule") or "").strip().upper()
    layout = str(game.get("card_layout_version", "")).strip()
    if rule == "LINE" and layout == "2":
        return "LINE"
    if rule == "FULL_CARD" and layout == "2":
        return "FULL_CARD"
    if rule == "LEGACY" and layout == "1":
        return "LEGACY"
    return "UNKNOWN"


def level_title(game: Mapping) -> str:
    return {"LOW": "سطح یک", "MEDIUM": "سطح دو", "HIGH": "سطح سه"}.get(
        game.get("game_level"), "سطح ثبت نشده"
    )


def draw_mode_title(game: Mapping) -> str:
    mode = game.get("draw_mode")
    if not mode:
        return "هنوز انتخاب نشده"
    return {"AUTO": "خودکار", "MANUAL": "دستی"}.get(mode, "نوع ثبت‌شده نامعتبر است")


def rule_title(game: Mapping | None) -> str:
    return {
        "LINE": "خطی",
        "FULL_CARD": "پرکردنی",
        "LEGACY": "قدیمی ۲۰عددی",
        "UNKNOWN": "قانون نامشخص",
    }[rule_kind(game)]


def rule_details(game: Mapping | None) -> str:
    return {
        "LINE": (
            "🃏 کارت ۱۵عددی، ۳ ردیف × ۹ ستون (۵ عدد در هر ردیف)\n"
            "🏆 تورنا: اعلام ۳ عدد از یک ردیف؛ خطی: اعلام هر ۵ عدد یک ردیف. سهم هر جایزه طبق تقسیم همین بازی است."
        ),
        "FULL_CARD": (
            "🃏 کارت ۱۵عددی، ۳ ردیف × ۹ ستون (۵ عدد در هر ردیف)\n"
            "🏆 پرکردنی: اعلام هر ۱۵ عدد کارت؛ بدون تورنا یا جایزه میانی"
        ),
        "LEGACY": (
            "🃏 کارت قدیمی ۲۰عددی، ۴ ردیف × ۵ ستون\n"
            "🏆 تورنا: تکمیل ستون ۴عددی؛ برد نهایی: تکمیل ردیف ۵عددی"
        ),
        "UNKNOWN": "⚠️ قانون یا چیدمان ثبت‌شدهٔ بازی ناقص یا ناسازگار است. برای بررسی با پشتیبانی تماس بگیرید.",
    }[rule_kind(game)]


def card_progress(numbers: list[int], called_numbers: list[int], game: Mapping | None) -> str:
    """Report observed matches, not an unverified win or payment."""
    nums = [int(n) for n in (numbers or [])]
    drawn = {int(n) for n in (called_numbers or [])}
    matches = sum(n > 0 and n in drawn for n in nums)
    usable = sum(n > 0 for n in nums)
    kind = rule_kind(game)
    lines = [f"✅ اعداد اعلام‌شده روی کارت: <b>{matches}/{usable}</b>"]
    width = 5 if kind == "LEGACY" else 9
    rows = [sum(n > 0 and n in drawn for n in nums[i:i + width]) for i in range(0, len(nums), width)]
    lines.append("📊 ردیف‌ها: " + " | ".join(f"{i}: {count}/۵" for i, count in enumerate(rows, 1)))
    return "\n".join(lines)
