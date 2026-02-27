# app/utils/tg_text.py
from __future__ import annotations

TG_SAFE_LIMIT = 3500


def chunk_text(text: str, limit: int = TG_SAFE_LIMIT) -> list[str]:
    """
    Backward-compatible chunker (خطی).
    ⚠️ این روش ممکن است وسط کارت / codeblock ببرد.
    برای پیام کارت‌ها از paginate_blocks استفاده کن.
    """
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    cur: list[str] = []
    cur_len = 0

    for line in text.splitlines(True):  # keepends
        if len(line) > limit:
            for i in range(0, len(line), limit):
                parts.append(line[i:i + limit])
            continue

        if cur_len + len(line) > limit:
            parts.append("".join(cur))
            cur = [line]
            cur_len = len(line)
        else:
            cur.append(line)
            cur_len += len(line)

    if cur:
        parts.append("".join(cur))


    return parts


def paginate_blocks(
    header_block: str,
    blocks: list[str],
    max_len: int = TG_SAFE_LIMIT,
    continuation_title: str = "📄 ادامه کارت‌های شما",
) -> list[str]:
    max_len = int(max_len or TG_SAFE_LIMIT)

    def cont_header(page_no: int) -> str:
        return f"{continuation_title} (صفحه {page_no})\n\n"

    def split_by_lines(prefix: str, text: str) -> list[str]:
        """Split text (line-based) so that each (prefix+chunk) <= max_len."""
        out: list[str] = []
        buf: list[str] = []
        buf_len = len(prefix)

        for ln in text.splitlines(True):  # keepends
            # اگر یک خط خیلی بلند شد، تکه تکه‌اش می‌کنیم
            if len(ln) > max_len:
                if buf:
                    out.append((prefix + "".join(buf)).rstrip())
                    buf, buf_len = [], len(prefix)

                for i in range(0, len(ln), max_len):
                    piece = ln[i:i + max_len]
                    # اینجا هم prefix را لحاظ می‌کنیم
                    if len(prefix) + len(piece) > max_len:
                        # prefix را برای این حالت حذف می‌کنیم (نادر)
                        out.append(piece.rstrip())
                    else:
                        out.append((prefix + piece).rstrip())
                continue

            if buf_len + len(ln) > max_len and buf:
                out.append((prefix + "".join(buf)).rstrip())
                buf = [ln]
                buf_len = len(prefix) + len(ln)
            else:
                buf.append(ln)
                buf_len += len(ln)

        if buf:
            out.append((prefix + "".join(buf)).rstrip())

        return [x for x in out if x]

    def push_part(parts: list[str], part: str) -> None:
        part = part.rstrip()
        if not part:
            return
        if len(part) <= max_len:
            parts.append(part)
            return
        # اگر از max_len رد کرد، line-based split (بدون header اضافه)
        parts.extend(split_by_lines("", part))

    parts: list[str] = []
    cur = (header_block or "").rstrip()
    page_no = 1

    for block in blocks:
        block = (block or "").rstrip()
        if not block:
            continue

        sep = "\n\n" if cur else ""
        candidate = f"{cur}{sep}{block}"

        if len(candidate) <= max_len:
            cur = candidate
            continue

        # اینجا candidate جا نشد، پس cur را finalize کن (با guard واقعی)
        if cur:
            push_part(parts, cur)
            page_no += 1

        # حالا part جدید: اول سعی کن با continuation header
        prefix = cont_header(page_no)
        new_cur = (prefix + block).rstrip()

        if len(new_cur) <= max_len:
            cur = new_cur
            continue

        # اگر header اضافه باعث overflow شد ولی خود block جا می‌شود، header را حذف کن
        if len(block) <= max_len:
            cur = block
            continue

        # اگر خود block هم بزرگ‌تر از max_len است (edge-case): split line-based با prefix
        split_parts = split_by_lines(prefix, block)
        if split_parts:
            # همه به جز آخری را مستقیم push کن، آخری را cur نگه دار تا شاید کارت بعدی جا بشه
            for sp in split_parts[:-1]:
                push_part(parts, sp)
                page_no += 1
                prefix = cont_header(page_no)
            cur = split_parts[-1]
        else:
            cur = prefix.rstrip()

    if cur:
        push_part(parts, cur)

    # sanity check سختگیرانه
    for p in parts:
        if len(p) > max_len:
            raise ValueError(f"paginate_blocks produced oversized part: {len(p)} > {max_len}")


    return parts
