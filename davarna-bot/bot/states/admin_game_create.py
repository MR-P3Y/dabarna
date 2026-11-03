from aiogram.fsm.state import State, StatesGroup


class AdminGameCreateSG(StatesGroup):
    waiting_card_price = State()
    waiting_commission_rate = State()
