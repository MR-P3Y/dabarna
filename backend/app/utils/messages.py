from __future__ import annotations

from typing import Optional


def money_toman(n: int) -> str:
    return f"{int(n):,} toman"


def _col_amount(state: dict) -> int:
    return int(state.get("col_prize_amount", 0) or 0)


def _row_amount(state: dict) -> int:
    return int(state.get("row_prize_amount", 0) or 0)


def format_game_lobby(game_state: dict) -> str:
    return (
        "Game lobby is ready\n"
        f"Game ID: `{game_state['game_id']}`\n"
        f"Card price: *{money_toman(game_state['card_price'])}*\n"
        f"Sales so far: *{money_toman(game_state['sold_amount'])}*\n"
        f"Prize pool: *{money_toman(game_state['prize_pool'])}*\n\n"
        "Buy cards to join."
    )


def format_game_running(game_state: dict) -> str:
    called = game_state.get("called_numbers", [])
    called_str = " - ".join(str(x) for x in called[-12:]) if called else "-"
    return (
        "Game is RUNNING\n"
        f"Game: `{game_state['game_id']}`\n"
        f"Card price: *{money_toman(game_state['card_price'])}*\n"
        f"Prize pool: *{money_toman(game_state['prize_pool'])}*\n"
        f"Column prize (30%): *{money_toman(_col_amount(game_state))}*\n"
        f"Row prize (60%): *{money_toman(_row_amount(game_state))}*\n\n"
        f"Called numbers: `{called_str}`\n"
        f"Last number: *{game_state.get('last_number') or '-'}*"
    )


def format_col_winner(game_state: dict) -> Optional[str]:
    col_paid = int(game_state.get("col_paid", 0) or 0)
    if not col_paid:
        return None

    winners = game_state.get("col_winner_user_ids") or []
    if not winners:
        return "Column prize paid."
    if len(winners) == 1:
        return f"Column win: `{winners[0]}`"
    return f"Column tie win: {', '.join(f'`{x}`' for x in winners)}"


def format_row_winner(game_state: dict) -> Optional[str]:
    row_paid = int(game_state.get("row_paid", 0) or 0)
    if not row_paid:
        return None

    winners = game_state.get("row_winner_user_ids") or []
    if not winners:
        return None

    amount = int(game_state.get("row_payout_total", _row_amount(game_state)) or 0)
    if len(winners) == 1:
        return f"Row win confirmed. Winner: `{winners[0]}`\nPaid: *{money_toman(amount)}*"
    return f"Row tie win confirmed. Winners: {', '.join(f'`{x}`' for x in winners)}\nPaid total: *{money_toman(amount)}*"
