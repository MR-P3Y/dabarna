from __future__ import annotations

import runpy
from pathlib import Path

TARGETS = [
    Path("davarna-bot/bot/keyboards/admin_games.py"),
    Path("davarna-bot/bot/routers/admin_draw_mode.py"),
    Path("davarna-bot/bot/routers/admin_games.py"),
]


def detect_format(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    body = raw[3:] if has_bom else raw
    crlf = body.count(b"\r\n")
    lf = body.count(b"\n") - crlf
    newline = "\r\n" if crlf >= lf else "\n"
    return newline, has_bom


def restore_format(path: Path, newline: str, has_bom: bool) -> None:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.decode("utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if newline == "\r\n":
        text = text.replace("\n", "\r\n")
    encoded = text.encode("utf-8")
    if has_bom:
        encoded = b"\xef\xbb\xbf" + encoded
    path.write_bytes(encoded)


formats = {path: detect_format(path) for path in TARGETS}
runpy.run_path("scripts/apply_admin_ui_refresh.py", run_name="__main__")
for path, (newline, has_bom) in formats.items():
    restore_format(path, newline, has_bom)
    print(f"format-restored {path} newline={newline!r} bom={has_bom}")
