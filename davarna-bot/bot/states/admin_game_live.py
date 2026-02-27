from aiogram.fsm.state import State, StatesGroup


class AdminGameLiveSG(StatesGroup):
    waiting_url = State()
