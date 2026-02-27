from pydantic import BaseModel, Field

class CreateDepositIn(BaseModel):
    amount: int

class UploadReceiptIn(BaseModel):
    receipt_file_id: str = Field(min_length=5)

class DepositOut(BaseModel):
    id: int
    user_id: int
    amount: int
    status: str
    receipt_file_id: str | None = None

class ApproveDepositIn(BaseModel):
    idempotency_key: str

class CreateWithdrawIn(BaseModel):
    amount: int
    full_name: str
    iban: str | None = None
    card_number: str
    account_number: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=6)

class WithdrawOut(BaseModel):
    id: int
    user_id: int
    amount: int
    status: str
    full_name: str
    iban: str
    card_number: str
    account_number: str
    paid_tracking: str | None = None

class ApproveWithdrawIn(BaseModel):
    idempotency_key: str

class MarkWithdrawPaidIn(BaseModel):
    paid_tracking: str


class RejectWithdrawIn(BaseModel):
    reason: str | None = None

# ========== Gateway Payment Schemas ==========

class InitiateGatewayPaymentIn(BaseModel):
    amount: int
    gateway: str = Field(
        description="Payment gateway: zarinpal, stripe, or paddlepay"
    )
    callback_url: str = Field(
        description="URL to redirect user after payment completion"
    )


class GatewayPaymentOut(BaseModel):
    id: int
    user_id: int
    amount: int
    gateway: str
    authority: str | None = None
    ref_id: str | None = None
    status: str
    wallet_tx_id: int | None = None
    created_at: str | None = None

    class Config:
        from_attributes = True


class VerifyGatewayPaymentIn(BaseModel):
    authority: str = Field(
        min_length=1,
        description="Payment authority/token from gateway"
    )
    ref_id: str = Field(
        min_length=1,
        description="Payment reference ID from gateway"
    )


class FailGatewayPaymentIn(BaseModel):
    authority: str
    ref_id: str
