from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.user import User

class UserService:
    @staticmethod
    def upsert(db: Session, tg_user_id: int, username=None, first_name=None, last_name=None) -> User:
        u = db.execute(select(User).where(User.tg_user_id == tg_user_id)).scalar_one_or_none()
        if u:
            u.username = username
            u.first_name = first_name
            u.last_name = last_name
            db.flush()
            return u

        u = User(
            tg_user_id=tg_user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        db.add(u)
        db.flush()
        return u
