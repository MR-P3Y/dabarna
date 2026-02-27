from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.user_guard import get_current_user_id
from app.schemas.user import UpsertUserIn, UserOut
from app.services.wallet_service import WalletService
from app.models.user import User

router = APIRouter(prefix="/users", tags=["users"])

@router.post("/upsert", response_model=UserOut)
def upsert_user(
    payload: UpsertUserIn,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    u = db.get(User, current_user_id)
    if not u:
        raise HTTPException(status_code=500, detail="user not found after telegram verification")

    WalletService.get_or_create_wallet(db, u.id)
    db.commit()
    return UserOut(
        id=u.id,
        tg_user_id=u.tg_user_id,
        username=u.username,
        first_name=u.first_name,
        last_name=u.last_name,
    )
