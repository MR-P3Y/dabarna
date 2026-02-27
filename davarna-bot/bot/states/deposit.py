from aiogram.fsm.state import State, StatesGroup

class DepositSG(StatesGroup):
    destination = State()
    amount = State()
    receipt = State()
    confirm = State()
