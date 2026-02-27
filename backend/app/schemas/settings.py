from pydantic import BaseModel

class SettingOut(BaseModel):
    k: str
    v_json: dict | list | int | float | str | bool

class SettingUpsertIn(BaseModel):
    v_json: dict | list | int | float | str | bool
