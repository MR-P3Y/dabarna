from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.keyboards.main_menu import main_menu_kb
from bot.services.html import h
from bot.services.ui import panel

router = Router()


@router.message(CommandStart(), F.chat.type == "private")
async def start(m: Message, is_admin: bool = False, is_super_admin: bool = False):
    name = m.from_user.full_name if m.from_user else "رفیق"
    text = panel(
        "به دورنای پیمون خوش اومدی",
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
