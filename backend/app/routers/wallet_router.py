# app/routers/wallet_router.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.user_guard import get_current_user_id
from app.schemas.wallet import WalletOut, WalletTxOut
from app.services.wallet_service import WalletService

router = APIRouter(prefix="/wallet", tags=["wallet"])


def _ensure_same_user(requested_user_id: int, current_user_id: int):
    if requested_user_id != current_user_id:
        raise HTTPException(status_code=403, detail="forbidden")


@router.get("/me", response_model=WalletOut)
def get_my_wallet(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return WalletService.get_wallet(db, current_user_id)


@router.get("/me/txs", response_model=list[WalletTxOut])
def list_my_txs(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return WalletService.list_txs(db, current_user_id)


# Backward compatible (secured)
@router.get("/{user_id}", response_model=WalletOut)
def get_wallet(
    user_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    _ensure_same_user(user_id, current_user_id)
    return WalletService.get_wallet(db, user_id)


@router.get("/{user_id}/txs", response_model=list[WalletTxOut])
def list_txs(
    user_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    _ensure_same_user(user_id, current_user_id)
    return WalletService.list_txs(db, user_id)
