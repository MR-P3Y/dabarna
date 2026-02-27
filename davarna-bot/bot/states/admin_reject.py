from aiogram.fsm.state import State, StatesGroup

class AdminRejectSG(StatesGroup):
    reason = State()
