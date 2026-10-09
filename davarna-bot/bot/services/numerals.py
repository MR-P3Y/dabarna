from __future__ import annotations

FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_TO_EN = str.maketrans(FA_DIGITS + AR_DIGITS, "0123456789" * 2)
_GROUP_SEPARATORS = {",", "٬", "،", "_", " "}


def normalize_digits(value: object) -> str:
    """Convert Persian/Arabic-Indic decimal digits to ASCII without changing other chars."""
    return str(value or "").translate(_TO_EN)


def normalize_integer_text(
    value: object,
    *,
    allow_sign: bool = False,
    allow_grouping: bool = False,
) -> str | None:
    text = normalize_digits(value).strip()
    if allow_grouping:
        text = "".join(ch for ch in text if ch not in _GROUP_SEPARATORS)
    if not text:
        return None
    if allow_sign and text.startswith("-"):
        digits = text[1:]
        if not digits or not digits.isascii() or not digits.isdigit():
            return None
        return "-" + digits
    if not text.isascii() or not text.isdigit():
        return None
    return text


def parse_int(
    value: object,
    *,
    allow_sign: bool = True,
    allow_grouping: bool = False,
) -> int | None:
    text = normalize_integer_text(
        value,
        allow_sign=allow_sign,
        allow_grouping=allow_grouping,
    )
    return int(text) if text is not None else None


def parse_positive_int(value: object, *, allow_grouping: bool = True) -> int | None:
    number = parse_int(value, allow_sign=False, allow_grouping=allow_grouping)
    return number if number is not None and number > 0 else None


def digits_only(value: object) -> str:
    """Return only canonical ASCII decimal digits from a localized numeric string."""
    return "".join(ch for ch in normalize_digits(value) if "0" <= ch <= "9")
