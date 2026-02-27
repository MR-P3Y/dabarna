from aiogram import F, Router
from aiogram.types import Message, CallbackQuery
import logging

from bot.keyboards.main_menu import main_menu_kb
from bot.services.ui import panel

router = Router()
log = logging.getLogger("bot.fallback")


@router.message(F.chat.type == "private")
async def any_message(m: Message, is_admin: bool = False, is_super_admin: bool = False):
    # هر متنی غیر از /start اینجا میاد
    await m.answer(
        panel(
            "منوی اصلی",
            "برای ادامه بازی از دکمه‌های منو استفاده کن 👇\n"
            "همه بخش‌ها آماده‌ست؛ فقط انتخاب کن و برو جلو 🎮",
        ),
        reply_markup=main_menu_kb(is_admin=is_admin, is_super_admin=is_super_admin),
        parse_mode="HTML",
    )


@router.callback_query()
async def any_callback(cq: CallbackQuery):
    # هر کال‌بکی که هندل نشده اینجا میاد
    log.warning("کالبک مدیریت‌نشده: %s", cq.data)
    await cq.answer("این گزینه فعلاً فعال نیست.", show_alert=False)
