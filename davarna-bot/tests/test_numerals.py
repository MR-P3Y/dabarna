from bot.services.numerals import digits_only, normalize_digits, parse_int, parse_positive_int


def test_normalize_digits():
    assert normalize_digits("۱۲۳") == "123"
    assert normalize_digits("١٢٣") == "123"
    assert normalize_digits("123") == "123"


def test_parse_positive_int_with_grouping():
    assert parse_positive_int("۵۰۰٬۰۰۰") == 500000
    assert parse_positive_int("500,000") == 500000
    assert parse_positive_int("۱۲ ۳۴۵") == 12345


def test_parse_int_strict_and_signed():
    assert parse_int("-۱۲", allow_sign=True) == -12
    assert parse_int("۱۲abc", allow_sign=False) is None


def test_digits_only():
    assert digits_only("IR۱۲۳-٤٥") == "12345"
