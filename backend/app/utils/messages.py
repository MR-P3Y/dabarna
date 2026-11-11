"""Persian game copy for the compatibility APIs and Telegram forum."""
from __future__ import annotations


def stored_rule(rule, layout) -> str:
    if type(layout) is int:
        if layout == 2 and rule in ("LINE", "FULL_CARD"):
            return rule
        if layout == 1 and rule == "LEGACY":
            return rule
    return "UNKNOWN"


RULE_ERROR = "قانون و ساختار ذخیره‌شدهٔ بازی ناقص یا ناسازگار است."
RULE_LINES = {
    "LINE": "🃏 کارت: <b>۳ ردیف × ۹ ستون، ۵ عدد در هر ردیف</b>\n🏆 برد: <b>تورنا ۳ عدد از یک ردیف؛ خطی ۵ عدد از یک ردیف</b>\n",
    "FULL_CARD": "🏆 قانون: <b>پرکردنی ۱۵ عدد کامل؛ بدون تورنا</b>\n",
    "LEGACY": "🃏 کارت قدیمی: <b>۴×۵، شامل ۲۰ عدد</b>\n🏆 برد قدیمی: <b>تورنا ستون ۴ عددی؛ تکمیل ردیف ۵ عددی</b>\n",
}
FINAL_LABEL = {"LINE": "خطی", "FULL_CARD": "پرکردنی", "LEGACY": "ردیفی"}


def money_toman(value) -> str:
    return f"{value:,} تومان" if type(value) is int and value >= 0 else "هنوز ثبت نشده"


def format_game_summary(state: dict) -> str:
    status = {"LOBBY": "در انتظار شروع", "RUNNING": "در حال بازی", "ENDED": "پایان‌یافته"}.get(state["status"], "وضعیت نامشخص")
    rule = stored_rule(state.get("game_rule"), state.get("card_layout_version"))
    lines = [f"بازی شماره {state['game_id']} | {status}"]
    if rule == "UNKNOWN":
        return "\n".join([*lines, RULE_ERROR])
    lines += [RULE_LINES[rule].strip().replace("<b>", "").replace("</b>", ""),
              f"قیمت کارت: {money_toman(state.get('card_price'))}",
              f"صندوق جایزه: {money_toman(state.get('prize_pool'))}"]
    if state["status"] == "LOBBY":
        lines.append(f"فروش تاکنون: {money_toman(state.get('sold_amount'))}")
    else:
        if rule != "FULL_CARD":
            lines.append(f"جایزه تورنا: {money_toman(state.get('col_prize_amount'))}")
        lines.append(f"جایزه {FINAL_LABEL[rule]}: {money_toman(state.get('row_prize_amount'))}")
        for bucket, label in (("col", "تورنا"), ("row", FINAL_LABEL[rule])):
            if bucket == "col" and rule == "FULL_CARD":
                continue
            if state.get(f"{bucket}_winner_card_ids") and state.get(f"{bucket}_paid") == 1:
                lines.append(f"مجموع پرداخت {label}: {money_toman(state.get(f'{bucket}_payout_total'))}")
        called = state.get("called_numbers") or []
        lines.append("اعداد اخیر (از تازه‌ترین): " + ("، ".join(map(str, called)) or "هنوز ثبت نشده"))
        last = state.get("last_number")
        lines.append(f"آخرین عدد: {last if last is not None else 'هنوز ثبت نشده'}")
    return "\n".join(lines)
