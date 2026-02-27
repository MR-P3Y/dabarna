from aiogram.fsm.state import State, StatesGroup


class AdminGameCloseSG(StatesGroup):
    waiting_reason = State()
