import html


def h(text: str) -> str:
    """Escape user-generated text for Telegram HTML parse mode."""
    return html.escape(text or "")
