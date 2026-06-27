from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.keyboards.join_gate import join_gate_action_kb
from bot.keyboards.main_menu import main_menu_kb
from bot.services.html import h
from bot.services.join_gate import configured_join_group_id, join_gate_body, resolve_join_gate_target
from bot.services.tg_membership import is_member
from bot.services.ui import panel

router = Router()


@router.message(CommandStart(), F.chat.type == "private")
async def start(
    m: Message,
    tg_user_id: int,
    is_admin: bool = False,
    is_super_admin: bool = False,
):
    name = m.from_user.full_name if m.from_user else "رفیق"

    if not (is_admin or is_super_admin):
        required_group_id = configured_join_group_id()
        if required_group_id is not None:
            member_ok = await is_member(m.bot, required_group_id, tg_user_id)
            if not member_ok:
                join_target = await resolve_join_gate_target(m.bot, required_group_id)
                await m.answer(
                    panel(
                        "عضویت اجباری",
                        join_gate_body(
                            "برای ورود به ربات و شروع بازی، ابتدا باید عضو گروه بازی باشید.",
                            join_target,
                        ),
                    ),
                    reply_markup=join_gate_action_kb(
                        "start",
                        required_group_id,
                        invite_link=join_target.invite_link,
                    ),
                    parse_mode="HTML",
                )
                return

    text = panel(
        "به دبرنای طوفان خوش اومدی",
        f"سلام <b>{h(name)}</b> 👋\n\n"
        "اینجا هر عدد می‌تونه ورق بازی رو برگردونه! 🎯\n"
        "کارت بخر 🃏، بازی زنده رو دنبال کن 📡 و برای برد جایزه آماده شو 🏆\n\n"
        "بزن بریم رفیق، بازی منتظرته 🔥👇",
    )
    await m.answer(
        text,
        reply_markup=main_menu_kb(is_admin=is_admin, is_super_admin=is_super_admin),
        parse_mode="HTML",
    )
