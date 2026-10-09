import re

from bot.services.numerals import normalize_digits, parse_positive_int


def parse_amount(text: str) -> int | None:
    return parse_positive_int(text, allow_grouping=True)


def normalize_iban(text: str) -> str | None:
    s = normalize_digits(text).strip().upper().replace(" ", "")
    if not re.fullmatch(r"IR\d{24}", s):
        return None
    return s


def normalize_card(text: str) -> str | None:
    s = normalize_digits(text).strip().replace("-", "").replace(" ", "")
    if not re.fullmatch(r"\d{16}", s):
        return None
    return s


def normalize_account(text: str) -> str | None:
    s = normalize_digits(text).strip().replace("-", "").replace(" ", "")
    if not re.fullmatch(r"\d{6,20}", s):
        return None
    return s


def normalize_name(text: str) -> str | None:
    s = (text or "").strip()
    if len(s) < 3:
        return None
    return s
