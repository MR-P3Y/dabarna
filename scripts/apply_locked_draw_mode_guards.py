from pathlib import Path

p = Path("backend/app/services/game_service.py")
s = p.read_text(encoding="utf-8")

if "manual calls are forbidden for locked AUTO games" in s and "draw mode must be selected before game start" in s:
    print("guards already present; nothing to do")
    raise SystemExit(0)

old = '''        # ✅ اگر قبلاً شروع شده/قفل شده: فقط state برگردان (هیچ event جدید نزن)\n        if str(game.status) != "LOBBY" or _safe_int(game.prize_locked) == 1:\n            return game\n\n        if int(game.sold_amount) <= 0:\n'''
new = '''        # ✅ اگر قبلاً شروع شده/قفل شده: فقط state برگردان (هیچ event جدید نزن)\n        if str(game.status) != "LOBBY" or _safe_int(game.prize_locked) == 1:\n            return game\n\n        draw_mode = str(game.draw_mode or "").upper()\n        auto_control = db.get(GameAutoDraw, int(game.id))\n        if draw_mode not in {"MANUAL", "AUTO"}:\n            raise HTTPException(status_code=400, detail="draw mode must be selected before game start")\n\n        if draw_mode == "AUTO":\n            interval = int(game.draw_interval_seconds or 0)\n            sequence = auto_control.sequence_json if auto_control is not None and isinstance(auto_control.sequence_json, list) else []\n            if interval not in {5, 8, 10, 15}:\n                raise HTTPException(status_code=400, detail="valid auto draw interval must be selected before game start")\n            if (\n                auto_control is None\n                or str(auto_control.status) != "ARMED"\n                or int(auto_control.interval_seconds or 0) != interval\n                or not sequence\n                or not str(auto_control.sequence_commitment or "").strip()\n            ):\n                raise HTTPException(status_code=400, detail="auto draw must be armed before game start")\n        elif game.draw_interval_seconds is not None:\n            raise HTTPException(status_code=400, detail="manual games cannot have an auto draw interval")\n\n        if int(game.sold_amount) <= 0:\n'''
assert old in s, "start_game insertion point not found"
s = s.replace(old, new, 1)

old = '''        game.row_winner_user_id = None\n        game.prize_locked = 1\n        game.status = "RUNNING"\n'''
new = '''        game.row_winner_user_id = None\n        game.prize_locked = 1\n        if game.draw_mode_locked_at is None:\n            game.draw_mode_locked_at = _utcnow_naive()\n        game.status = "RUNNING"\n'''
assert old in s, "start_game lock point not found"
s = s.replace(old, new, 1)

old = '''                    "row_prize_amount": int(game.row_prize_amount),\n                },\n'''
new = '''                    "row_prize_amount": int(game.row_prize_amount),\n                    "draw_mode": draw_mode,\n                    "draw_interval_seconds": int(game.draw_interval_seconds) if game.draw_interval_seconds is not None else None,\n                    "sequence_commitment": str(auto_control.sequence_commitment) if auto_control is not None and auto_control.sequence_commitment else None,\n                },\n'''
assert old in s, "GAME_STARTED payload point not found"
s = s.replace(old, new, 1)

old = '''            if str(game.status) != "RUNNING":\n                raise HTTPException(status_code=400, detail="game is not RUNNING")\n            auto_control = db.get(GameAutoDraw, int(game_id))\n            if (\n                str(source or "MANUAL").upper() != "AUTO"\n                and auto_control is not None\n                and str(auto_control.status) == "RUNNING"\n            ):\n                raise HTTPException(status_code=409, detail="pause auto draw before a manual call")\n'''
new = '''            if str(game.status) != "RUNNING":\n                raise HTTPException(status_code=400, detail="game is not RUNNING")\n\n            source_norm = str(source or "MANUAL").upper()\n            draw_mode = str(game.draw_mode or "").upper()\n            if game.draw_mode_locked_at is not None:\n                if draw_mode == "AUTO" and source_norm != "AUTO":\n                    raise HTTPException(status_code=409, detail="manual calls are forbidden for locked AUTO games")\n                if draw_mode == "MANUAL" and source_norm == "AUTO":\n                    raise HTTPException(status_code=409, detail="automatic calls are forbidden for locked MANUAL games")\n\n            auto_control = db.get(GameAutoDraw, int(game_id))\n            if (\n                source_norm != "AUTO"\n                and auto_control is not None\n                and str(auto_control.status) == "RUNNING"\n            ):\n                raise HTTPException(status_code=409, detail="pause auto draw before a manual call")\n'''
assert old in s, "call_number guard point not found"
s = s.replace(old, new, 1)

old = '''                        "number": int(number),\n                        "called_number_id": int(row.id),\n                    },\n'''
new = '''                        "number": int(number),\n                        "called_number_id": int(row.id),\n                        "source": source_norm,\n                    },\n'''
assert old in s, "NUMBER_CALLED payload point not found"
s = s.replace(old, new, 1)

old = '''            if not _can_manage_game(game, admin_user_id, can_manage_any=can_manage_any):\n                raise HTTPException(status_code=403, detail="only game admin can undo call")\n            auto_control = db.get(GameAutoDraw, int(game_id))\n'''
new = '''            if not _can_manage_game(game, admin_user_id, can_manage_any=can_manage_any):\n                raise HTTPException(status_code=403, detail="only game admin can undo call")\n            if str(game.draw_mode or "").upper() == "AUTO" and game.draw_mode_locked_at is not None:\n                raise HTTPException(status_code=409, detail="undo is forbidden for locked AUTO games")\n            auto_control = db.get(GameAutoDraw, int(game_id))\n'''
assert old in s, "undo guard point not found"
s = s.replace(old, new, 1)

p.write_text(s, encoding="utf-8")
print("patched", p)
