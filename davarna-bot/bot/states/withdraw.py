from aiogram.fsm.state import State, StatesGroup

class WithdrawSG(StatesGroup):
    amount = State()
    full_name = State()
    card_number = State()
    iban = State()
    account_number = State()
    confirm = State()
