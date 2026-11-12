from aiogram.fsm.state import State, StatesGroup


class SuperAdminManageSG(StatesGroup):
    waiting_for_tg_user_id = State()
    waiting_for_role = State()
    waiting_for_display_name = State()
    waiting_for_deposit_card_payload = State()
    waiting_for_crypto_address = State()
    waiting_for_crypto_activation_confirmation = State()
    waiting_for_crypto_cancellation_confirmation = State()
