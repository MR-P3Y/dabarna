from aiogram.fsm.state import State, StatesGroup

class AdminCallSG(StatesGroup):
    waiting_number = State()
