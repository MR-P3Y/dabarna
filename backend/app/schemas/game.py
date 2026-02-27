from typing import List, Optional
from pydantic import BaseModel, Field

class CreateGameIn(BaseModel):
    tg_group_id: int | None = None
    tg_topic_id: int | None = None
    card_price: int

class GameOut(BaseModel):
    id: int
    tg_group_id: int
    tg_topic_id: int | None = None
    status: str
    admin_user_id: int
    card_price: int
    sold_amount: int
    commission_amount: int
    prize_pool: int
    prize_locked: int
    col_prize_amount: int
    row_prize_amount: int
    col_paid: int
    row_paid: int

class BuyCardsIn(BaseModel):
    qty: int = Field(ge=1, le=50)
    idempotency_key: str = Field(min_length=6)

class BuyCardsOut(BaseModel):
    game_id: int
    purchase_id: int
    qty: int
    total_price: int
    wallet_tx_id: int
    prize_pool: int

class StartGameIn(BaseModel):
    idempotency_key: str = Field(min_length=6)

class CallNumberIn(BaseModel):
    number: int
    idempotency_key: str = Field(min_length=6)

class CallNumberOut(BaseModel):
    game_id: int
    number: int
    called_count: int
    col_paid: int
    row_paid: int
    row_winner_user_ids: list[int] | None = None
    row_winner_card_ids: list[int] | None = None


class CardOut(BaseModel):
    card_id: int
    fingerprint: str
    numbers: list[int]  # 20 عدد row-major (5×4)

class MyCardsOut(BaseModel):
    game_id: int
    cards: list[CardOut]

class GameStateOut(BaseModel):
    game_id: int
    tg_group_id: int
    tg_topic_id: int | None = None
    status: str
    card_price: int
    sold_amount: int
    commission_amount: int
    prize_pool: int
    prize_locked: int
    col_prize_amount: int
    row_prize_amount: int
    called_numbers: list[int]
    last_number: int | None = None
    col_paid: int
    row_paid: int
    col_winner_user_ids: list[int] = []
    col_winner_card_ids: list[int] = []
    row_winner_card_ids: list[int] = []
    row_winner_user_ids: list[int] = []
    col_payout_total: int | None = None
    row_payout_total: int | None = None

class CardPreviewOut(BaseModel):
    card_id: int
    fingerprint: str
    grid_text: str

class MyCardsPreviewOut(BaseModel):
    game_id: int
    called_numbers: list[int]
    cards: list[CardPreviewOut]


class GroupMessageOut(BaseModel):
    game_id: int
    mode: str  # LOBBY | RUNNING | ENDED
    text: str

class TgMessageOut(BaseModel):
    game_id: int
    mode: str
    parse_mode: str = "MarkdownV2"
    text: str
    parts: Optional[List[str]] = None
