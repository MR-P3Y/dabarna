FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
TO_EN = str.maketrans(FA_DIGITS + AR_DIGITS, "0123456789" * 2)


def normalize_digits(value: object) -> str:
    return str(value or "").translate(TO_EN)


def clean_numeric(value: object) -> str:
    return normalize_digits(value).strip().replace(" ", "").replace("-", "")
