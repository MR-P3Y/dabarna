from aiogram.fsm.state import State, StatesGroup


class SuperAdminManageSG(StatesGroup):
    waiting_for_tg_user_id = State()
    waiting_for_display_name = State()
    waiting_for_deposit_card_payload = State()
