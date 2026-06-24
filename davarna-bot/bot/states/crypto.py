from aiogram.fsm.state import State, StatesGroup


class CryptoDepositSG(StatesGroup):
    amount = State()
    tx_hash = State()


class CryptoAdminSG(StatesGroup):
    reject_reason = State()
