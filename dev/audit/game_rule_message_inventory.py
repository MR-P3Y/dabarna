#!/usr/bin/env python3
"""Read-only inventory for #25/#27/#29; produces review locations, not PASS claims."""
from __future__ import annotations
import argparse
import pathlib
import re

SOURCES = {
    "Bot notifier": "davarna-bot/bot/workers/notifier.py",
    "Bot topics": "davarna-bot/bot/services/user_topics.py",
    "Bot help": "davarna-bot/bot/routers/help.py",
    "Mini App JS": "backend/app/static/mini/app.js",
    "Mini API": "backend/app/routers/mini_router.py",
    "Game logic": "backend/app/services/game_service.py",
    "Autopilot": "backend/app/services/game_autopilot_worker.py",
}
PATTERN = re.compile(
    r"game_rule|FULL_CARD|LEGACY|TORNA|PRIZE_COL|PRIZE_ROW|"
    r"USER_TOPIC_|send_to_user_topic|announce_before_seconds|"
    r"\b(?:۱۵|۲۰|15|20)\s*(?:عدد|number)|تورنا|پرکردنی|خطی",
    flags=re.IGNORECASE,
)


def scan(root: pathlib.Path, *, max_hits: int = 20) -> str:
    lines = [
        "# DAVARNA game-rule / Telegram content source inventory",
        "",
        "Automated source **candidates**, not runtime compliance results.",
        "",
        "| Surface | File | Matched lines | Review samples |",
        "|---|---|---:|---|",
    ]
    for surface, rel in SOURCES.items():
        path = root / rel
        if not path.is_file():
            lines.append(f"| {surface} | `{rel}` | MISSING | Source path needs verification |")
            continue
        hits = [
            (no, text.strip())
            for no, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if PATTERN.search(text)
        ]
        examples = ", ".join(str(n) for n, _ in hits[:max_hits])
        lines.append(f"| {surface} | `{rel}` | {len(hits)} | {examples or '—'} |")
    lines.extend([
        "",
        "## Review gates",
        "",
        "- Rule-specific text must derive from persisted `game_rule` and card version.",
        "- LOW/MEDIUM = LINE 3×9 (15 numbers); HIGH = FULL_CARD (15); LEGACY historical 4×5 (20).",
        "- Do not promise a 5-minute notice for player-triggered starts without a confirmed start time.",
        "- Verify topic IDs read-only before changing announcement routing.",
        "- Ensure notifier and API use durable deduplication events for GAME_CREATED/STARTED/ENDED.",
        "- Mark findings PASS/FIX/NOT_TESTED only after tracing real payloads and tests.",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[2])
    parser.add_argument("--max-hits", type=int, default=20)
    args = parser.parse_args()
    print(scan(args.root.resolve(), max_hits=max(1, args.max_hits)))
