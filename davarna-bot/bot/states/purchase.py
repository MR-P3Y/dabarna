from aiogram.fsm.state import State, StatesGroup

class PurchaseSG(StatesGroup):
    select_game = State()
    select_qty = State()
    confirm = State()
