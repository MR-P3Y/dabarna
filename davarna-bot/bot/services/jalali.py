from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_TO_EN = str.maketrans(_FA_DIGITS + _AR_DIGITS, "0123456789" * 2)
_TO_FA = str.maketrans("0123456789", _FA_DIGITS)
_DATE_RE = re.compile(
    r"(?P<y>\d{4})[-/](?P<m>\d{1,2})[-/](?P<d>\d{1,2})"
    r"(?:[ T](?P<h>\d{1,2}):(?P<mi>\d{1,2})(?::(?P<s>\d{1,2}))?)?"
)


def _to_fa_digits(value: object) -> str:
    return str(value).translate(_TO_FA)


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    j_days_in_month = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]

    gy -= 1600
    gm -= 1
    gd -= 1

    g_day_no = 365 * gy + (gy + 3) // 4 - (gy + 99) // 100 + (gy + 399) // 400
    for i in range(gm):
        g_day_no += g_days_in_month[i]
    if gm > 1 and ((gy + 1600) % 4 == 0 and ((gy + 1600) % 100 != 0 or (gy + 1600) % 400 == 0)):
        g_day_no += 1
    g_day_no += gd

    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053

    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461

    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    jm = 0
    while jm < 11 and j_day_no >= j_days_in_month[jm]:
        j_day_no -= j_days_in_month[jm]
        jm += 1

    return jy, jm + 1, j_day_no + 1


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    g_days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    j_days_in_month = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]

    jy -= 979
    jm -= 1
    jd -= 1

    j_day_no = 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4
    for i in range(jm):
        j_day_no += j_days_in_month[i]
    j_day_no += jd

    g_day_no = j_day_no + 79
    gy = 1600 + 400 * (g_day_no // 146097)
    g_day_no %= 146097

    leap = True
    if g_day_no >= 36525:
        g_day_no -= 1
        gy += 100 * (g_day_no // 36524)
        g_day_no %= 36524
        if g_day_no >= 365:
            g_day_no += 1
        else:
            leap = False

    gy += 4 * (g_day_no // 1461)
    g_day_no %= 1461

    if g_day_no >= 366:
        leap = False
        g_day_no -= 1
        gy += g_day_no // 365
        g_day_no %= 365

    gm = 0
    while gm < 11:
        days = g_days_in_month[gm] + (1 if gm == 1 and leap else 0)
        if g_day_no < days:
            break
        g_day_no -= days
        gm += 1

    return gy, gm + 1, g_day_no + 1


def _format_parts(jy: int, jm: int, jd: int, hour: int | None, minute: int | None, second: int | None, *, seconds: bool) -> str:
    date_text = f"{jy:04d}/{jm:02d}/{jd:02d}"
    if hour is None or minute is None:
        return _to_fa_digits(date_text)
    if seconds and second is not None:
        return _to_fa_digits(f"{date_text} {hour:02d}:{minute:02d}:{second:02d}")
    return _to_fa_digits(f"{date_text} {hour:02d}:{minute:02d}")


def format_jalali_datetime(value: object, *, default: str = "—", seconds: bool = False, tz_name: str | None = None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return default

    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is not None and tz_name:
            try:
                dt = dt.astimezone(ZoneInfo(tz_name))
            except Exception:
                pass
        jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
        return _format_parts(jy, jm, jd, dt.hour, dt.minute, dt.second, seconds=seconds)

    normalized = raw.translate(_TO_EN).replace("T", " ")
    normalized = normalized.replace("Z", "").split(".", 1)[0].strip()
    m = _DATE_RE.search(normalized)
    if not m:
        return raw

    y = int(m.group("y"))
    month = int(m.group("m"))
    day = int(m.group("d"))
    hour = int(m.group("h")) if m.group("h") is not None else None
    minute = int(m.group("mi")) if m.group("mi") is not None else None
    second = int(m.group("s")) if m.group("s") is not None else None

    if 1200 <= y <= 1499:
        jy, jm, jd = y, month, day
    else:
        try:
            jy, jm, jd = gregorian_to_jalali(y, month, day)
        except Exception:
            return raw
    return _format_parts(jy, jm, jd, hour, minute, second, seconds=seconds)


def jalali_date_to_gregorian_text(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    normalized = raw.translate(_TO_EN).replace("/", "-")
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", normalized)
    if not m:
        return normalized
    y, month, day = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if 1200 <= y <= 1499:
        gy, gm, gd = jalali_to_gregorian(y, month, day)
        return f"{gy:04d}-{gm:02d}-{gd:02d}"
    return f"{y:04d}-{month:02d}-{day:02d}"
