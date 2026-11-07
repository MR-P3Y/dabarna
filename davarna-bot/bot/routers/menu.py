from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.keyboards.main_menu import main_menu_kb
from bot.services.telegram_safe import safe_edit_or_send
from bot.services.ui import panel

router = Router()


@router.callback_query(F.data == "nav:menu", F.message.chat.type == "private")
async def back_to_menu(
    cq: CallbackQuery,
    state: FSMContext,
    is_admin: bool = False,
    is_super_admin: bool = False,
    is_game_admin: bool = False,
    is_finance_admin: bool = False,
    is_user_admin: bool = False,
):
    await state.clear()
    text = panel(
        "منوی اصلی",
        "برای خرید کارت، دیدن کارت‌ها و کیف پول از همین منو استفاده کن.\n"
        "راهنمای تاپیک‌های گروه هم در بخش «راهنما» است.\n"
        "یک گزینه انتخاب کن 👇",
    )
    await safe_edit_or_send(
        cq.message,
        text,
        reply_markup=main_menu_kb(
            is_admin=is_admin,
            is_super_admin=is_super_admin,
            is_game_admin=is_game_admin,
            is_finance_admin=is_finance_admin,
            is_user_admin=is_user_admin,
        ),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data == "nav:menu")
async def back_to_menu_group_block(cq: CallbackQuery):
    await cq.answer("منوی نقش‌دار فقط در گفت‌وگوی خصوصی ربات قابل نمایش است.", show_alert=True)
