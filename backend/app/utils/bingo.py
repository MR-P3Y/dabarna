import hashlib
import json
from typing import Iterable

DEFAULT_ROWS = 4
DEFAULT_COLS = 5

def generate_card_numbers(seed: str, max_number: int = 90, count: int = 20) -> list[int]:
    """
    تولید count عدد یکتا بین 1..max_number
    """
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    nums: list[int] = []
    i = 0
    while len(nums) < count:
        chunk = h[i:i+2]
        if len(chunk) < 2:
            h = hashlib.sha256(h.encode("utf-8")).hexdigest()
            i = 0
            continue
        n = int(chunk, 16) % max_number + 1
        if n not in nums:
            nums.append(n)
        i += 2
        if i >= len(h):
            h = hashlib.sha256(h.encode("utf-8")).hexdigest()
            i = 0
    return nums

def card_fingerprint(numbers: list[int]) -> str:
    raw = json.dumps(numbers, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def _as_set(called: Iterable[int]) -> set[int]:
    return set(int(x) for x in called)

def check_line(numbers: list[int], called: Iterable[int], rows: int = DEFAULT_ROWS, cols: int = DEFAULT_COLS, mode: str = "ANY") -> bool:
    """
    mode:
      ROW: فقط ردیف‌ها
      COL: فقط ستون‌ها
      ANY: ردیف یا ستون
    numbers: لیست 20 تایی به صورت Row-major (4 ردیف، هر ردیف 5 عدد)
    """
    if len(numbers) != rows * cols:
        return False
    cset = _as_set(called)

    mode = mode.upper().strip()
    if mode in ("ROW", "ANY"):
        for r in range(rows):
            row = numbers[r*cols:(r+1)*cols]
            if all(n in cset for n in row):
                return True

    if mode in ("COL", "ANY"):
        for col in range(cols):
            col_nums = [numbers[r*cols + col] for r in range(rows)]
            if all(n in cset for n in col_nums):
                return True

    return False

def check_full(numbers: list[int], called: Iterable[int]) -> bool:
    cset = _as_set(called)
    return all(n in cset for n in numbers)
