from app.utils.numerals import clean_numeric, normalize_digits


def test_normalize_digits():
    assert normalize_digits("۱۲۳") == "123"
    assert normalize_digits("١٢٣") == "123"
    assert normalize_digits("123") == "123"


def test_clean_numeric():
    assert clean_numeric("۶۰۳۷-۹۹۹۹-١٢٣٤-٥٦٧٨") == "6037999912345678"
    assert clean_numeric(" ۱۲۳ ۴۵۶ ") == "123456"
