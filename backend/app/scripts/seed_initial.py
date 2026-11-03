import json
from sqlalchemy import select
from app.core.db import SessionLocal
from app.models.rbac import Role
from app.models.settings import AppSetting

DEFAULT_SETTINGS = {
    "allowed_topup_amounts": [50000, 100000, 200000, 500000, 1000000],
    "max_cards_per_purchase": 50,
    "card_rows": 5,
    "card_cols": 4,
    "numbers_per_card": 20,
    "max_number": 90,
}

def main():
    db = SessionLocal()
    try:
        # roles
        for r in ["SUPER_ADMIN", "ADMIN", "GAME_OPERATOR", "FINANCE_ADMIN"]:
            exists = db.execute(select(Role).where(Role.name == r)).scalar_one_or_none()
            if not exists:
                db.add(Role(name=r))
        db.commit()

        # settings
        for k, v in DEFAULT_SETTINGS.items():
            s = db.get(AppSetting, k)
            if not s:
                db.add(AppSetting(k=k, v_json=v))
        db.commit()

        print("Seed done ✅")
    finally:
        db.close()

if __name__ == "__main__":
    main()
