from __future__ import annotations

import re


_DIRECT_SUBSTRINGS: list[tuple[str, str]] = [
    ("cannot start: no cards sold", "امکان شروع بازی نیست: هنوز هیچ کارتی خریداری نشده است."),
    ("game is not running", "بازی در حال اجرا نیست."),
    ("game is not in lobby", "بازی در وضعیت انتظار شروع نیست."),
    ("game not found", "بازی پیدا نشد."),
    ("no active game", "بازی فعالی برای این گروه پیدا نشد."),
    ("tg_group_id mismatch", "شناسه گروه ارسالی با مسیر درخواست یکسان نیست."),
    ("tg_topic_id mismatch", "شناسه تاپیک ارسالی با مسیر درخواست یکسان نیست."),
    ("cannot close lobby game: cards already sold", "این بازی خرید داشته و قابل بستن نیست."),
    ("cannot close lobby game: numbers already called", "برای این بازی عدد اعلام شده و قابل بستن نیست."),
    ("only lobby game can be closed", "فقط بازی در وضعیت لابی قابل بستن است."),
    ("only game admin can start", "فقط ادمین همین بازی می تواند بازی را شروع کند."),
    ("only game admin can call number", "فقط ادمین همین بازی می تواند عدد اعلام کند."),
    ("only game admin can undo call", "فقط ادمین همین بازی می تواند بازگردانی انجام دهد."),
    ("only game admin can close lobby game", "فقط ادمین همین بازی می تواند بازی لابی را ببندد."),
    ("no called number to undo", "شماره ای برای بازگردانی وجود ندارد."),
    ("call locked, try again", "عملیات اعلام عدد در حال انجام است؛ چند لحظه بعد دوباره تلاش کن."),
    ("call/undo locked, try again", "عملیات اعلام/بازگردانی در حال انجام است؛ چند لحظه بعد دوباره تلاش کن."),
    ("prize locked", "جایزه قفل شده و این عملیات مجاز نیست."),
    ("failed to generate unique card after retries", "تولید کارت یکتا ناموفق بود. دوباره تلاش کن."),
    ("insufficient available balance", "موجودی قابل برداشت کافی نیست."),
    ("insufficient balance", "موجودی کافی نیست."),
    ("wallet not found", "کیف پول پیدا نشد."),
    ("wallet balance became negative", "خطای داخلی کیف پول رخ داد."),
    ("invalid iban", "شماره شبا نامعتبر است."),
    ("invalid card_number", "شماره کارت نامعتبر است."),
    ("invalid account_number", "شماره حساب نامعتبر است."),
    ("invalid full_name", "نام و نام خانوادگی نامعتبر است."),
    ("invalid user_id", "شناسه کاربر نامعتبر است."),
    ("amount must be > 0", "مبلغ باید بیشتر از صفر باشد."),
    ("amount must be positive", "مبلغ باید بیشتر از صفر باشد."),
    ("destination_id is required", "انتخاب کارت مقصد الزامی است."),
    ("invalid destination_id", "کارت مقصد انتخاب‌شده نامعتبر است."),
    ("destination not found", "کارت مقصد پیدا نشد."),
    ("invalid destination card_number", "شماره کارت مقصد نامعتبر است."),
    ("at least one active destination is required", "حداقل یک کارت مقصد فعال باید وجود داشته باشد."),
    ("cannot delete last destination", "حذف آخرین کارت مقصد مجاز نیست."),
    ("quantity must be positive", "تعداد باید بیشتر از صفر باشد."),
    ("idempotency_key is required", "کلید یکتای درخواست الزامی است."),
    ("deposit_request not found", "درخواست واریز پیدا نشد."),
    ("withdraw_request not found", "درخواست برداشت پیدا نشد."),
    ("deposit_request not awaiting receipt", "درخواست واریز در وضعیت دریافت رسید نیست."),
    ("deposit_request not ready", "درخواست واریز آماده این عملیات نیست."),
    ("withdraw_request not pending", "درخواست برداشت در وضعیت در انتظار نیست."),
    ("withdraw_request not approved", "درخواست برداشت تایید نشده است."),
    ("invalid status", "وضعیت درخواست نامعتبر است."),
    ("already approved", "این درخواست قبلا تایید شده است."),
    ("already rejected", "این درخواست قبلا رد شده است."),
    ("forbidden", "اجازه دسترسی نداری."),
    ("missing authorization", "مجوز دسترسی ارسال نشده است."),
    ("missing user authorization", "مجوز کاربر ارسال نشده است."),
    ("missing user header", "هدر کاربر ارسال نشده است."),
    ("missing telegram init data", "اطلاعات ورود تلگرام ارسال نشده است."),
    ("telegram bot token not configured", "توکن ربات تلگرام روی سرور تنظیم نشده است."),
    ("invalid telegram user id", "شناسه کاربر تلگرام نامعتبر است."),
    ("missing x-bot-token header", "هدر احراز هویت سرویس ربات ارسال نشده است."),
    ("invalid bot token", "توکن سرویس ربات نامعتبر است."),
    ("missing x-tg-user-id header", "شناسه کاربر تلگرام ارسال نشده است."),
    ("invalid x-tg-user-id format", "فرمت شناسه کاربر تلگرام نامعتبر است."),
    ("admin api token is not configured", "توکن ادمین تنظیم نشده است."),
    ("super admin api token is not configured", "توکن سوپرادمین تنظیم نشده است."),
    ("super admin required", "این عملیات فقط برای سوپرادمین مجاز است."),
    ("super admin owner required", "این عملیات فقط برای سوپرادمین اصلی مجاز است."),
    ("only game admin can manage live link", "فقط ادمین همان بازی می‌تواند لینک لایو را مدیریت کند."),
    ("live_url is required", "لینک لایو الزامی است."),
    ("invalid live_url", "لینک لایو نامعتبر است."),
    ("live_url is too long", "طول لینک لایو بیش از حد مجاز است."),
    ("rbac owner is not configured", "مالک سوپرادمین برای مدیریت نقش‌ها تنظیم نشده است."),
    ("cannot revoke your own super admin role", "امکان حذف نقش سوپرادمین از حساب خودت وجود ندارد."),
    ("cannot revoke last super admin", "امکان حذف آخرین سوپرادمین وجود ندارد."),
    ("user not found", "کاربر پیدا نشد."),
    ("admin account not found", "حساب ادمین پیدا نشد."),
    ("is not seeded", "نقش دسترسی در بک‌اند مقداردهی اولیه نشده است."),
    ("backend timeout", "پاسخ بک اند دیر رسید. لطفا دوباره تلاش کن."),
    ("request failed", "درخواست ناموفق بود. لطفا دوباره تلاش کن."),
    ("both from_at and to_at are required", "زمان شروع و پایان گزارش باید وارد شود."),
    ("receipt file missing on disk", "فایل رسید در سرور پیدا نشد."),
    ("receipt not found", "رسید پیدا نشد."),
    ("status endpoint currently supports only running or ended", "در حال حاضر فقط تغییر وضعیت به در حال اجرا یا پایان‌یافته پشتیبانی می‌شود."),
]


_DIRECT_REGEX: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^number must be 1\.\.\d+$", re.IGNORECASE), "عدد باید در بازه مجاز بازی باشد."),
    (re.compile(r"^qty must be 1\.\.\d+$", re.IGNORECASE), "تعداد کارت باید در بازه مجاز باشد."),
    (re.compile(r"^invalid status:\s*.+$", re.IGNORECASE), "وضعیت انتخاب شده نامعتبر است."),
    (re.compile(r"^invalid date filter:\s*.+$", re.IGNORECASE), "بازه تاریخ نامعتبر است."),
    (re.compile(r"^limit must be between \d+ and \d+$", re.IGNORECASE), "تعداد آیتم درخواستی نامعتبر است."),
    (re.compile(r"^limit must be >= \d+$", re.IGNORECASE), "حداکثر تعداد آیتم نامعتبر است."),
    (re.compile(r"^offset must be >= 0$", re.IGNORECASE), "آفست صفحه بندی نامعتبر است."),
    (re.compile(r"^page must be >= 1$", re.IGNORECASE), "شماره صفحه نامعتبر است."),
    (re.compile(r"^page_size must be between \d+ and \d+$", re.IGNORECASE), "اندازه صفحه نامعتبر است."),
    (re.compile(r"^min_amount cannot be greater than max_amount$", re.IGNORECASE), "حداقل مبلغ نمی تواند از حداکثر مبلغ بیشتر باشد."),
    (re.compile(r"^created_from cannot be greater than created_to$", re.IGNORECASE), "تاریخ شروع نمی تواند بعد از تاریخ پایان باشد."),
    (re.compile(r"^amount must be one of .+$", re.IGNORECASE), "مبلغ باید یکی از مقادیر مجاز باشد."),
    (re.compile(r"^gateway must be one of .+$", re.IGNORECASE), "درگاه پرداخت نامعتبر است."),
    (re.compile(r"^payment already .+$", re.IGNORECASE), "این پرداخت قبلا پردازش شده است."),
    (re.compile(r"^setting '.+' is locked while a game is running$", re.IGNORECASE), "این تنظیمات هنگام اجرای بازی قفل است."),
]

_FAILED_WRAPPER = re.compile(r"^[a-z0-9_ \-]+ failed:\s*(.+)$", re.IGNORECASE)


def _contains_persian(text: str) -> bool:
    return bool(re.search(r"[؀-ۿ]", text))


def _contains_latin(text: str) -> bool:
    return bool(re.search(r"[a-zA-Z]", text))


def _status_fallback(status: int) -> str:
    if status == 400:
        return "درخواست نامعتبر است."
    if status == 401:
        return "احراز هویت نامعتبر است."
    if status == 403:
        return "اجازه دسترسی نداری."
    if status == 404:
        return "مورد درخواستی پیدا نشد."
    if status == 409:
        return "این عملیات در تعارض با وضعیت فعلی است. چند لحظه بعد دوباره تلاش کن."
    if status >= 500:
        return "خطای داخلی سرویس رخ داد. کمی بعد دوباره تلاش کن."
    return "خطا در ارتباط با سرویس."


def localize_api_error_detail(detail: str, *, status: int) -> str:
    raw = str(detail or "").strip()
    if not raw:
        return _status_fallback(status)
    if _contains_persian(raw):
        return raw

    lower = raw.lower()

    if lower.startswith("backend unavailable"):
        return "ارتباط با بک اند برقرار نیست. چند لحظه بعد دوباره تلاش کن."

    m_failed = _FAILED_WRAPPER.match(raw)
    if m_failed:
        tail = localize_api_error_detail(m_failed.group(1), status=status)
        return f"عملیات ناموفق بود: {tail}"

    for needle, fa in _DIRECT_SUBSTRINGS:
        if needle in lower:
            return fa

    for rx, fa in _DIRECT_REGEX:
        if rx.match(raw):
            return fa

    if _contains_latin(raw):
        return _status_fallback(status)
    return raw

