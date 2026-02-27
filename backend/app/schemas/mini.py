from __future__ import annotations

from pydantic import BaseModel, Field


class MiniAuthExchangeIn(BaseModel):
    init_data: str | None = None


class MiniAuthExchangeOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_at: int
    expires_in: int
    user_id: int


class MiniGameItemOut(BaseModel):
    id: int
    tg_group_id: int
    tg_topic_id: int | None = None
    status: str
    card_price: int
    sold_amount: int
    prize_pool: int
    col_prize_amount: int
    row_prize_amount: int
    created_at: str | None = None


class MiniGameListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[MiniGameItemOut]


class MiniEventOut(BaseModel):
    id: int
    game_id: int
    kind: str
    payload: dict | None = None
    created_at: str


class MiniCardOut(BaseModel):
    card_id: int
    fingerprint: str
    numbers: list[int]


class MiniUserCardItemOut(BaseModel):
    game_id: int
    card_id: int
    fingerprint: str
    numbers: list[int]
    game_status: str
    card_price: int
    created_at: str | None = None


class MiniUserCardListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[MiniUserCardItemOut]


class MiniGameSnapshotOut(BaseModel):
    game: MiniGameItemOut
    state: dict
    my_cards: list[MiniCardOut]
    last_event_id: int
    recent_events: list[MiniEventOut]


class MiniBuyIn(BaseModel):
    qty: int = Field(ge=1, le=50)
    idempotency_key: str = Field(min_length=6)


class MiniBuyOut(BaseModel):
    game_id: int
    purchase_id: int
    qty: int
    total_price: int
    wallet_tx_id: int
    prize_pool: int


class MiniWalletOut(BaseModel):
    user_id: int
    balance: int
    updated_at: str | None = None


class MiniWalletTxOut(BaseModel):
    id: int
    direction: str
    amount: int
    reason: str
    ref_type: str | None = None
    ref_id: int | None = None
    created_at: str


class MiniDepositCreateIn(BaseModel):
    amount: int
    destination_id: str | None = None


class MiniDepositReceiptIn(BaseModel):
    filename: str
    content_type: str
    data_base64: str


class MiniDepositOut(BaseModel):
    id: int
    amount: int
    status: str
    receipt_uploaded: bool
    destination_id: str | None = None
    destination_title: str | None = None
    created_at: str | None = None


class MiniDepositDestinationOut(BaseModel):
    id: str
    title: str
    account_name: str
    bank_name: str
    iban: str
    card_number: str
    account_number: str
    is_active: bool = True


class MiniDepositDestinationListOut(BaseModel):
    total: int
    items: list[MiniDepositDestinationOut]
    instructions: str | None = None


class MiniDepositListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[MiniDepositOut]


class MiniWithdrawCreateIn(BaseModel):
    amount: int = Field(gt=0)
    full_name: str
    iban: str | None = None
    card_number: str
    account_number: str | None = None
    idempotency_key: str = Field(min_length=6)


class MiniWithdrawOut(BaseModel):
    id: int
    amount: int
    status: str
    created_at: str | None = None


class MiniWithdrawListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[MiniWithdrawOut]


class MiniNearestToWinOut(BaseModel):
    card_id: int | None = None
    user_id: int | None = None
    called_count: int = 0
    total_numbers: int = 0
    percent: int = 0
    missing: int = 0


class MiniRecentGameStatOut(BaseModel):
    game_id: int
    card_price: int = 0
    sold_cards: int
    sold_amount: int = 0
    commission_amount: int = 0
    prize_pool: int
    winners_count: int
    col_prize_total: int = 0
    row_prize_total: int = 0
    col_winners_count: int = 0
    row_winners_count: int = 0
    col_winner_amount: int = 0
    row_winner_amount: int = 0
    win_pattern: str


class MiniLatestWinOut(BaseModel):
    user_alias: str
    amount: int
    game_id: int | None = None
    at: str | None = None


class MiniTrustStatsOut(BaseModel):
    total_paid_today: int
    winners_today: int
    latest_win: MiniLatestWinOut | None = None


class MiniDashboardInsightsOut(BaseModel):
    hot_game_id: int | None = None
    hot_threshold_cards: int = 10
    in_game: bool = False
    recent_winner: bool = False
    recent_games: list[MiniRecentGameStatOut]
    trust: MiniTrustStatsOut
