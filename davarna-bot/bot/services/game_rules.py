"""Single source of truth for user-facing game rules in the Telegram bot.

Always use the rule stored on the *game*. A forum topic name is not proof of
a game's rule; historical 4x5 cards remain LEGACY.
"""
from __future__ import annotations

from collections.abc import Mapping


def rule_kind(game: Mapping | None) -> str:
    game = game or {}
    rule = str(game.get("game_rule") or "").strip().upper()
    try:
        layout = int(game.get("card_layout_version") or 1)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if rule == "LINE" and layout == 2:
        return "LINE"
    if rule == "FULL_CARD" and layout == 2:
        return "FULL_CARD"
    if rule == "LEGACY" and layout == 1:
        return "LEGACY"
    return "UNKNOWN"


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
            "🏆 تورنا: اعلام ۳ عدد از یک ردیف؛ خطی: اعلام ۵ عدد همان ردیف"
        ),
        "FULL_CARD": (
            "🃏 کارت ۱۵عددی، ۳ ردیف × ۹ ستون (۵ عدد در هر ردیف)\n"
            "🏆 پرکردنی: اعلام هر ۱۵ عدد کارت؛ بدون تورنا یا جایزه میانی"
        ),
        "LEGACY": (
            "🃏 کارت قدیمی ۲۰عددی، ۴ ردیف × ۵ ستون\n"
            "🏆 تورنا: تکمیل ستون ۴عددی؛ برد نهایی: تکمیل ردیف ۵عددی"
        ),
        "UNKNOWN": "⚠️ قانون ثبت‌شده این بازی قابل تشخیص نیست؛ قبل از خرید بررسی کنید.",
    }[rule_kind(game)]


def card_progress(numbers: list[int], called_numbers: list[int], game: Mapping | None) -> str:
    """Report observed matches, not an unverified win or payment."""
    nums = [int(n) for n in (numbers or [])]
    drawn = {int(n) for n in (called_numbers or [])}
    matches = sum(n > 0 and n in drawn for n in nums)
    usable = sum(n > 0 for n in nums)
    kind = rule_kind(game)
    lines = [f"✅ اعداد اعلام‌شده روی کارت: <b>{matches}/{usable}</b>"]
    if kind == "LINE" and len(nums) == 27:
        rows = [
            sum(n > 0 and n in drawn for n in nums[i * 9:(i + 1) * 9])
            for i in range(3)
        ]
        lines.append("📊 ردیف‌ها: " + " | ".join(f"{i + 1}: {count}/۵" for i, count in enumerate(rows)))
    elif kind == "FULL_CARD" and len(nums) == 27:
        lines.append("🎯 هدف: تکمیل هر ۱۵ عدد؛ تورنا ندارد")
    elif kind == "LEGACY" and len(nums) == 20:
        lines.append("🎯 قانون قدیمی: تورنا با ستون ۴عددی، برد نهایی با ردیف ۵عددی")
    return "\n".join(lines)
