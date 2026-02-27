from __future__ import annotations

from typing import Iterable, Tuple, List

from app.utils.tg_markdown import md2_escape


def _money(n: int) -> str:
    return f"{int(n):,}"


def group_message_running(
    game_id: int,
    card_price: int,
    prize_pool: int,
    col_prize_amount: int,
    row_prize_amount: int,
    called_numbers: Iterable[int],
    last_number: int | None,
) -> str:
    called = list(called_numbers)
    called_txt = ", ".join(str(x) for x in called) if called else "-"
    last_txt = str(last_number) if last_number is not None else "-"

    return (
        f"*{md2_escape('Game is RUNNING')}*\n"
        f"{md2_escape('Game')}: `{game_id}`\n"
        f"{md2_escape('Card price')}: *{_money(card_price)} {md2_escape('toman')}*\n"
        f"{md2_escape('Prize pool')}: *{_money(prize_pool)} {md2_escape('toman')}*\n"
        f"{md2_escape('Column prize (30%)')}: *{_money(col_prize_amount)} {md2_escape('toman')}*\n"
        f"{md2_escape('Row prize (60%)')}: *{_money(row_prize_amount)} {md2_escape('toman')}*\n\n"
        f"{md2_escape('Called numbers')}: `{called_txt}`\n"
        f"{md2_escape('Last number')}: *{last_txt}*"
    )


def private_cards_preview(
    game_id: int,
    user_id: int,
    called_numbers: Iterable[int],
    cards: list[dict],
) -> str:
    called = list(called_numbers)
    called_txt = ", ".join(str(x) for x in called) if called else "-"

    lines = [
        f"*{md2_escape('Your cards')}*",
        f"{md2_escape('Game')}: `{game_id}`",
        f"{md2_escape('User')}: `{user_id}`",
        f"{md2_escape('Called numbers')}: `{called_txt}`",
        "",
    ]

    if not cards:
        lines.append(f"- {md2_escape('You do not have cards yet.')}")
        return "\n".join(lines).rstrip()

    for c in cards:
        card_id = int(c["card_id"])
        fp = str(c["fingerprint"])
        grid_text = str(c["grid_text"]).rstrip()
        safe_grid = grid_text.replace("```", "```")

        lines.append(f"*{md2_escape('Card')}* `{card_id}`")
        lines.append(f"*{md2_escape('Fingerprint')}:* `{fp}`")
        lines.append("```")
        lines.append(safe_grid)
        lines.append("```")
        lines.append("")

    return "\n".join(lines).rstrip()


def announce_col_winners(game_id: int, winners: list[int], each: int, total: int) -> str:
    winners_txt = ", ".join(str(x) for x in winners)
    return (
        f"*{md2_escape('Column payout done')}*\n"
        f"{md2_escape('Game')}: `{game_id}`\n"
        f"{md2_escape('Winners')}: `{winners_txt}`\n"
        f"{md2_escape('Each share')}: *{_money(each)} {md2_escape('toman')}*\n"
        f"{md2_escape('Total paid')}: *{_money(total)} {md2_escape('toman')}*"
    )


def announce_row_winner(
    game_id: int,
    winner_user_id: int,
    amount: int,
    card_id: int | None = None,
    fingerprint: str | None = None,
) -> str:
    extra = ""
    if card_id is not None and fingerprint:
        extra = (
            f"\n{md2_escape('Winner card')}: `{card_id}`\n"
            f"{md2_escape('Fingerprint')}: `{fingerprint}`"
        )

    return (
        f"*{md2_escape('Row payout done')}*\n"
        f"{md2_escape('Game')}: `{game_id}`\n"
        f"{md2_escape('Winner')}: `{winner_user_id}`\n"
        f"{md2_escape('Amount')}: *{_money(amount)} {md2_escape('toman')}*"
        f"{extra}"
    )


def build_private_cards_blocks(
    game_id: int,
    user_id: int,
    called_numbers: Iterable[int],
    cards: list[dict],
) -> Tuple[str, List[str]]:
    called = list(called_numbers)
    called_txt = ", ".join(str(x) for x in called) if called else "-"

    header_lines = [
        f"*{md2_escape('Your cards')}*",
        f"{md2_escape('Game')}: `{game_id}`",
        f"{md2_escape('User')}: `{user_id}`",
        f"{md2_escape('Called numbers')}: `{called_txt}`",
        "",
    ]
    header_block = "\n".join(header_lines).rstrip()

    blocks: List[str] = []
    if not cards:
        blocks.append(f"- {md2_escape('You do not have cards yet.')}")
        return header_block, blocks

    for c in cards:
        card_id = int(c["card_id"])
        fp = str(c["fingerprint"])
        grid_text = str(c["grid_text"]).rstrip()
        safe_grid = grid_text.replace("```", "```")

        block_lines = [
            f"*{md2_escape('Card')}* `{card_id}`",
            f"*{md2_escape('Fingerprint')}:* `{fp}`",
            "```",
            safe_grid,
            "```",
        ]
        blocks.append("\n".join(block_lines).rstrip())

    return header_block, blocks
