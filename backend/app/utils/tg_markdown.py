# app/utils/tg_markdown.py
from __future__ import annotations

import re

_MD2_SPECIALS = r'[_*\[\]()~`>#+\-=|{}.!]'

def md2_escape(text: str) -> str:
    """Escape text for Telegram MarkdownV2."""
    if text is None:
        return ""
    return re.sub(_MD2_SPECIALS, lambda m: "\\" + m.group(0), str(text))
