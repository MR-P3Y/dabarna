from aiogram import Router
from aiogram.types import CallbackQuery
import logging

router = Router()
log = logging.getLogger("bot.cb")

@router.callback_query()
async def cb_fallback(cq: CallbackQuery):
    log.warning("کالبک ناشناخته: %s", cq.data)
    await cq.answer("این دکمه فعلاً پشتیبانی نمی‌شود.", show_alert=False)
