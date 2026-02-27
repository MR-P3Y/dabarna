from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.purchase import qty_kb
from bot.services.tg_membership import is_member
from bot.services.ui import panel

router = Router()

_ACTION_TARGETS: dict[str, tuple[str, str]] = {
    "games": ("بازی‌های فعال", "menu:games"),
    "buy": ("خرید کارت", "menu:buy"),
    "deposit": ("واریز", "menu:deposit"),
    "withdraw": ("برداشت", "menu:withdraw"),
}


def _continue_after_join_kb(action_title: str, action_callback_data: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=f"➡️ ورود به {action_title}", callback_data=action_callback_data)
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1, 1)
    return kb.as_markup()


@router.callback_query(F.data.regexp(r"^join:check:action:[a-z_]+:-?\d+$"))
async def join_check_action(cq: CallbackQuery, tg_user_id: int):
    try:
        _, _, _, action_key, chat_id_s = (cq.data or "").split(":")
        chat_id = int(chat_id_s)
    except Exception:
        await cq.answer("داده نامعتبر است.", show_alert=False)
        return

    target = _ACTION_TARGETS.get(action_key)
    if target is None:
        await cq.answer("عملیات نامعتبر است.", show_alert=False)
        return

    ok = await is_member(cq.bot, chat_id, tg_user_id)
    if not ok:
        await cq.answer("هنوز عضو گروه نشدی. اول وارد گروه شو.", show_alert=True)
        return

    action_title, action_callback_data = target
    await cq.answer("عضویت تایید شد ✅", show_alert=False)
    await cq.message.edit_text(
        panel(
            "عضویت تایید شد",
            f"✅ عضویت شما تایید شد.\n"
            f"برای ادامه روی «ورود به {action_title}» بزن.",
        ),
        parse_mode="HTML",
        reply_markup=_continue_after_join_kb(action_title, action_callback_data),
    )


@router.callback_query(F.data.regexp(r"^join:check:\d+:-?\d+$"))
async def join_check(cq: CallbackQuery, state: FSMContext, tg_user_id: int):
    _, _, game_id_s, chat_id_s = (cq.data or "").split(":")
    game_id = int(game_id_s)
    chat_id = int(chat_id_s)

    ok = await is_member(cq.bot, chat_id, tg_user_id)
    if not ok:
        await cq.answer("هنوز عضو نشدی. اول وارد گروه شو.", show_alert=True)
        return

    await cq.answer("عضویت تایید شد ✅", show_alert=False)
    await cq.message.edit_text(
        panel("خرید کارت", "عضویت تایید شد.\nحالا تعداد کارت را انتخاب کن:"),
        parse_mode="HTML",
        reply_markup=qty_kb(game_id),
    )
