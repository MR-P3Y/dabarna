from pydantic import BaseModel

class UpsertUserIn(BaseModel):
    pass

class UserOut(BaseModel):
    id: int
    tg_user_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
