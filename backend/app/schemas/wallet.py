from pydantic import BaseModel, Field

class WalletOut(BaseModel):
    user_id: int
    balance: int

class WalletTxOut(BaseModel):
    id: int
    direction: str
    amount: int
    reason: str
    ref_type: str | None = None
    ref_id: int | None = None
    idempotency_key: str
    created_at: str
