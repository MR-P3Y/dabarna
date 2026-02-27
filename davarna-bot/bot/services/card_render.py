from html import escape
import re

def build_grid_text_from_numbers(numbers: list[int], cols: int = 5) -> str:
    """
    خروجی: 4 ردیف × 5 ستون (برای 20 عدد)
    """
    nums = [int(x) for x in (numbers or [])]
    if len(nums) != 20:
        # اگر تعداد فرق داشت هم باز می‌سازیم، ولی 20 ایده‌آله
        pass

    rows = []
    for i in range(0, len(nums), cols):
        row = nums[i:i + cols]
        # عرض ثابت برای مرتب بودن
        rows.append("  ".join(f"{n:>2}" for n in row))
    return "\n".join(rows)

def render_grid_with_marks(grid_text: str, called_numbers: list[int]) -> str:
    called = set(int(x) for x in (called_numbers or []))

    def repl(m: re.Match) -> str:
        n = int(m.group(0))
        return f"{n}✅" if n in called else str(n)

    marked = re.sub(r"\b\d+\b", repl, grid_text or "")
    return escape(marked)
