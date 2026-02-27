import re

def parse_amount(text: str) -> int | None:
    # اجازه می‌دهیم کاربر "5,000" هم بزند
    s = (text or "").strip().replace(",", "").replace(" ", "")
    if not s.isdigit():
        return None
    amount = int(s)
    if amount <= 0:
        return None
    return amount

def normalize_iban(text: str) -> str | None:
    s = (text or "").strip().upper().replace(" ", "")
    # ایران: IR + 24 رقم => 26 کاراکتر
    if not re.fullmatch(r"IR\d{24}", s):
        return None
    return s

def normalize_card(text: str) -> str | None:
    s = (text or "").strip().replace("-", "").replace(" ", "")
    if not re.fullmatch(r"\d{16}", s):
        return None
    return s

def normalize_account(text: str) -> str | None:
    s = (text or "").strip().replace("-", "").replace(" ", "")
    # چون بانک‌ها متفاوتن، سخت‌گیری زیاد نمی‌کنیم: 6 تا 20 رقم
    if not re.fullmatch(r"\d{6,20}", s):
        return None
    return s

def normalize_name(text: str) -> str | None:
    s = (text or "").strip()
    if len(s) < 3:
        return None
    return s
