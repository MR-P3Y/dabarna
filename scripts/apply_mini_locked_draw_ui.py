from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _variant(text: str, eol: bytes) -> bytes:
    return text.replace("\n", eol.decode("ascii")).encode("utf-8")


def replace_once(rel: str, old: str, new: str) -> None:
    path = ROOT / rel
    data = path.read_bytes()
    for eol in (b"\r\n", b"\n"):
        old_b = _variant(old, eol)
        count = data.count(old_b)
        if count == 1:
            new_b = _variant(new, eol)
            path.write_bytes(data.replace(old_b, new_b, 1))
            print(f"patched {rel}")
            return
        if count > 1:
            raise SystemExit(f"refusing ambiguous replacement in {rel}: {count} matches")
    raise SystemExit(f"target block not found in {rel}")


def main() -> None:
    replace_once(
        "backend/app/routers/mini_router.py",
        "from app.services.game_auto_draw_service import AUTO_DRAW_INTERVALS, GameAutoDrawService\nfrom app.services.wallet_service import WalletService",
        "from app.services.game_auto_draw_service import AUTO_DRAW_INTERVALS, GameAutoDrawService\nfrom app.services.game_draw_mode_service import GameDrawModeService\nfrom app.services.wallet_service import WalletService",
    )

    replace_once(
        "backend/app/routers/mini_router.py",
        "class MiniAdminAutoDrawStartIn(BaseModel):\n    interval_seconds: int = Field(default=10)",
        "class MiniAdminDrawModeIn(BaseModel):\n    draw_mode: str\n    interval_seconds: int | None = None\n\n\nclass MiniAdminAutoDrawStartIn(BaseModel):\n    interval_seconds: int = Field(default=10)",
    )

    replace_once(
        "backend/app/routers/mini_router.py",
        "@router.get(\"/admin/games/{game_id}/auto-draw\")\ndef mini_admin_auto_draw_state(\n    game_id: int,\n    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),\n    db: Session = Depends(get_db),\n):\n    _mini_require_game_manage_access(db, int(game_id), ident)\n    return GameAutoDrawService.get(db, int(game_id))",
        "@router.get(\"/admin/games/{game_id}/draw-mode\")\ndef mini_admin_draw_mode_state(\n    game_id: int,\n    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),\n    db: Session = Depends(get_db),\n):\n    _mini_require_game_manage_access(db, int(game_id), ident)\n    return GameDrawModeService.state(db, int(game_id))\n\n\n@router.put(\"/admin/games/{game_id}/draw-mode\")\ndef mini_admin_set_draw_mode(\n    game_id: int,\n    payload: MiniAdminDrawModeIn,\n    request: Request,\n    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),\n    db: Session = Depends(get_db),\n):\n    _mini_require_game_manage_access(db, int(game_id), ident)\n    max_number = int(GameService._get_setting(db, GameService.KEY_MAX_NUMBER, 90))\n    try:\n        state = GameDrawModeService.select_mode(\n            db,\n            game_id=int(game_id),\n            admin_user_id=int(ident.user_id),\n            draw_mode=str(payload.draw_mode),\n            interval_seconds=payload.interval_seconds,\n            max_number=max_number,\n            can_manage_any=bool(ident.is_super_admin),\n        )\n        AdminAuditService.record(\n            db,\n            admin=_mini_to_admin_identity(ident),\n            action=\"game.draw_mode.select\",\n            target_type=\"game\",\n            target_id=int(game_id),\n            request=request,\n            details={\n                \"game_id\": int(game_id),\n                \"draw_mode\": state.get(\"draw_mode\"),\n                \"interval_seconds\": state.get(\"interval_seconds\"),\n                \"sequence_commitment\": state.get(\"sequence_commitment\"),\n                \"locked\": bool(state.get(\"locked\")),\n            },\n        )\n        db.commit()\n        return state\n    except HTTPException:\n        db.rollback()\n        raise\n    except Exception as exc:\n        db.rollback()\n        raise HTTPException(status_code=500, detail=f\"انتخاب روش شماره‌خوانی ناموفق بود: {exc}\")\n\n\n@router.get(\"/admin/games/{game_id}/auto-draw\")\ndef mini_admin_auto_draw_state(\n    game_id: int,\n    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),\n    db: Session = Depends(get_db),\n):\n    _mini_require_game_manage_access(db, int(game_id), ident)\n    return GameAutoDrawService.get(db, int(game_id))",
    )

    replace_once(
        "backend/app/static/mini/index.html",
        """                  <label for=\"adminAutoDrawInterval\">فاصله اعلام اعداد</label>\n                  <select id=\"adminAutoDrawInterval\">\n                    <option value=\"5\">۵ ثانیه</option>\n                    <option value=\"8\">۸ ثانیه</option>\n                    <option value=\"10\" selected>۱۰ ثانیه</option>\n                    <option value=\"15\">۱۵ ثانیه</option>\n                  </select>\n                  <div class=\"admin-action-row\">\n                    <button id=\"adminAutoDrawStartBtn\" class=\"small-btn primary\" type=\"button\">شروع خودکار</button>\n                    <button id=\"adminAutoDrawPauseBtn\" class=\"small-btn\" type=\"button\">توقف موقت</button>\n                    <button id=\"adminAutoDrawResumeBtn\" class=\"small-btn\" type=\"button\">ادامه</button>\n                    <button id=\"adminAutoDrawStopBtn\" class=\"small-btn danger\" type=\"button\">پایان خودکار</button>\n                  </div>\n                  <div id=\"adminAutoDrawHint\" class=\"step-hint action-local-hint\"></div>""",
        """                  <div class=\"admin-auto-draw-head\">\n                    <div>\n                      <span>روش بازی</span>\n                      <strong id=\"adminDrawModeLabel\">انتخاب نشده</strong>\n                    </div>\n                    <div>\n                      <span>قفل روش</span>\n                      <strong id=\"adminDrawModeLock\">آزاد تا شروع</strong>\n                    </div>\n                    <div>\n                      <span>شناسه ترتیب</span>\n                      <strong id=\"adminDrawCommitment\">-</strong>\n                    </div>\n                  </div>\n                  <label for=\"adminAutoDrawInterval\">فاصله اعلام خودکار</label>\n                  <select id=\"adminAutoDrawInterval\">\n                    <option value=\"5\">۵ ثانیه</option>\n                    <option value=\"8\">۸ ثانیه</option>\n                    <option value=\"10\" selected>۱۰ ثانیه</option>\n                    <option value=\"15\">۱۵ ثانیه</option>\n                  </select>\n                  <div class=\"admin-action-row\">\n                    <button id=\"adminDrawModeManualBtn\" class=\"small-btn\" type=\"button\">👤 انتخاب دستی</button>\n                    <button id=\"adminDrawModeAutoBtn\" class=\"small-btn primary\" type=\"button\">🤖 انتخاب خودکار</button>\n                    <button id=\"adminAutoDrawPauseBtn\" class=\"small-btn\" type=\"button\">⏸ مکث خودکار</button>\n                    <button id=\"adminAutoDrawResumeBtn\" class=\"small-btn\" type=\"button\">▶️ ادامه همان ترتیب</button>\n                  </div>\n                  <div id=\"adminAutoDrawHint\" class=\"step-hint action-local-hint\">روش شماره‌خوانی را قبل از شروع بازی انتخاب کنید.</div>""",
    )

    replace_once(
        "backend/app/static/mini/index.html",
        '<script src="./app.js?v=auto-draw-20260916" type="module"></script>',
        '<script src="./app.js?v=locked-draw-20260916-1" type="module"></script>',
    )

    replace_once(
        "backend/app/static/mini/app.js",
        """  const autoDraw = state.admin?.autoDrawByGame?.get(gid) || null;\n  const autoStatus = String(autoDraw?.status || \"STOPPED\").toUpperCase();\n\n  const hasLiveLink = Boolean(adminLiveLinkForGame(gid));\n\n  setBtn(\"adminStartBtn\", hasGame && isLobby, hasGame ? \"شروع فقط برای بازی در لابی فعال است.\" : \"ابتدا بازی را انتخاب کنید.\");\n  setBtn(\"adminCloseLobbyBtn\", hasGame && isLobby, hasGame ? \"لغو فقط پیش از شروع بازی مجاز است.\" : \"ابتدا بازی را انتخاب کنید.\");\n  setBtn(\"adminCallBtn\", hasGame && isRunning && autoStatus !== \"RUNNING\", autoStatus === \"RUNNING\" ? \"ابتدا شماره‌خوان خودکار را متوقف موقت کنید.\" : \"اعلام عدد فقط برای بازی در حال اجرا مجاز است.\");\n  setBtn(\"adminUndoBtn\", hasGame && isRunning && autoStatus !== \"RUNNING\", autoStatus === \"RUNNING\" ? \"ابتدا شماره‌خوان خودکار را متوقف موقت کنید.\" : \"حذف آخرین عدد فقط برای بازی در حال اجرا مجاز است.\");\n  setBtn(\"adminAutoDrawStartBtn\", hasGame && isRunning && autoStatus === \"STOPPED\", \"شروع شماره‌خوان خودکار\");\n  setBtn(\"adminAutoDrawPauseBtn\", hasGame && isRunning && autoStatus === \"RUNNING\", \"توقف موقت شماره‌خوان\");\n  setBtn(\"adminAutoDrawResumeBtn\", hasGame && isRunning && autoStatus === \"PAUSED\", \"ادامه شماره‌خوان\");\n  setBtn(\"adminAutoDrawStopBtn\", hasGame && isRunning && autoStatus !== \"STOPPED\", \"پایان حالت خودکار و بازگشت به دستی\");""",
        """  const autoDraw = state.admin?.autoDrawByGame?.get(gid) || null;\n  const autoStatus = String(autoDraw?.auto_status || autoDraw?.status || \"STOPPED\").toUpperCase();\n  const drawMode = String(autoDraw?.draw_mode || \"\").toUpperCase();\n  const drawLocked = Boolean(autoDraw?.locked);\n  const validDrawMode = drawMode === \"MANUAL\" || drawMode === \"AUTO\";\n\n  const hasLiveLink = Boolean(adminLiveLinkForGame(gid));\n\n  setBtn(\"adminStartBtn\", hasGame && isLobby && validDrawMode, !validDrawMode ? \"قبل از شروع، روش شماره‌خوانی را انتخاب کنید.\" : \"شروع فقط برای بازی در لابی فعال است.\");\n  setBtn(\"adminCloseLobbyBtn\", hasGame && isLobby, hasGame ? \"لغو فقط پیش از شروع بازی مجاز است.\" : \"ابتدا بازی را انتخاب کنید.\");\n  setBtn(\"adminCallBtn\", hasGame && isRunning && drawMode === \"MANUAL\", drawMode === \"AUTO\" ? \"این بازی روی حالت خودکار قفل شده است.\" : \"اعلام عدد فقط برای بازی دستی در حال اجرا مجاز است.\");\n  setBtn(\"adminUndoBtn\", hasGame && isRunning && drawMode === \"MANUAL\", drawMode === \"AUTO\" ? \"Undo در بازی خودکار قفل‌شده مجاز نیست.\" : \"حذف آخرین عدد فقط برای بازی دستی در حال اجرا مجاز است.\");\n  setBtn(\"adminDrawModeManualBtn\", hasGame && isLobby && !drawLocked, \"حالت دستی فقط پیش از شروع قابل انتخاب است.\");\n  setBtn(\"adminDrawModeAutoBtn\", hasGame && isLobby && !drawLocked, \"حالت خودکار و فاصله فقط پیش از شروع قابل انتخاب است.\");\n  setBtn(\"adminAutoDrawPauseBtn\", hasGame && isRunning && drawMode === \"AUTO\" && autoStatus === \"RUNNING\", \"مکث شماره‌خوان خودکار؛ ترتیب اعداد تغییر نمی‌کند.\");\n  setBtn(\"adminAutoDrawResumeBtn\", hasGame && isRunning && drawMode === \"AUTO\" && autoStatus === \"PAUSED\", \"ادامه همان ترتیب قفل‌شده.\");\n\n  const intervalEl = getEl(\"adminAutoDrawInterval\");\n  if (intervalEl) intervalEl.disabled = !(hasGame && isLobby && !drawLocked);""",
    )

    replace_once(
        "backend/app/static/mini/app.js",
        """async function adminStartGame() {\n  const { gid } = requireAdminGameStatus([\"LOBBY\"], \"شروع بازی\");\n  setAdminLocalHint(\"adminCallActionHint\", \"در حال شروع بازی...\");""",
        """async function adminStartGame() {\n  const { gid } = requireAdminGameStatus([\"LOBBY\"], \"شروع بازی\");\n  const draw = adminAutoDrawState(gid) || {};\n  const drawMode = String(draw.draw_mode || \"\").toUpperCase();\n  if (drawMode !== \"MANUAL\" && drawMode !== \"AUTO\") {\n    throw new Error(\"قبل از شروع بازی، روش شماره‌خوانی دستی یا خودکار را انتخاب کنید.\");\n  }\n  setAdminLocalHint(\"adminCallActionHint\", \"در حال شروع بازی...\");""",
    )

    replace_once(
        "backend/app/static/mini/app.js",
        """  setAdminLocalHint(\"adminCallActionHint\", `بازی #${gid} شروع شد.`, \"success\");\n  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid)]);""",
        """  setAdminLocalHint(\"adminCallActionHint\", `بازی #${gid} شروع شد و روش شماره‌خوانی قفل شد.`, \"success\");\n  await Promise.allSettled([refreshAdminGames(), refreshAdminAutoDraw(gid), openLiveGame(gid)]);""",
    )

    replace_once(
        "backend/app/static/mini/app.js",
        """function renderAdminAutoDraw() {\n  const gid = Number(state.admin?.selectedGameId || 0);\n  const data = adminAutoDrawState(gid) || {};\n  const status = String(data.status || \"STOPPED\").toUpperCase();\n  const labels = { RUNNING: \"در حال اجرا\", PAUSED: \"متوقف موقت\", STOPPED: \"متوقف\" };\n  const statusEl = getEl(\"adminAutoDrawStatus\");\n  const remainingEl = getEl(\"adminAutoDrawRemaining\");\n  const countdownEl = getEl(\"adminAutoDrawCountdown\");\n  const intervalEl = getEl(\"adminAutoDrawInterval\");\n  if (statusEl) statusEl.textContent = labels[status] || status;\n  if (remainingEl) remainingEl.textContent = Number.isFinite(Number(data.remaining_count)) ? String(Number(data.remaining_count)) : \"-\";\n  if (intervalEl && data.interval_seconds && document.activeElement !== intervalEl) {\n    intervalEl.value = String(data.interval_seconds);\n  }""",
        """function renderAdminAutoDraw() {\n  const gid = Number(state.admin?.selectedGameId || 0);\n  const data = adminAutoDrawState(gid) || {};\n  const status = String(data.auto_status || data.status || \"STOPPED\").toUpperCase();\n  const drawMode = String(data.draw_mode || \"\").toUpperCase();\n  const locked = Boolean(data.locked);\n  const labels = { ARMED: \"آماده شروع\", RUNNING: \"در حال اجرا\", PAUSED: \"متوقف موقت\", STOPPED: \"متوقف\" };\n  const statusEl = getEl(\"adminAutoDrawStatus\");\n  const remainingEl = getEl(\"adminAutoDrawRemaining\");\n  const countdownEl = getEl(\"adminAutoDrawCountdown\");\n  const intervalEl = getEl(\"adminAutoDrawInterval\");\n  const modeEl = getEl(\"adminDrawModeLabel\");\n  const lockEl = getEl(\"adminDrawModeLock\");\n  const commitmentEl = getEl(\"adminDrawCommitment\");\n  const manualBtn = getEl(\"adminDrawModeManualBtn\");\n  const autoBtn = getEl(\"adminDrawModeAutoBtn\");\n  if (statusEl) statusEl.textContent = drawMode === \"MANUAL\" ? \"دستی\" : (labels[status] || status);\n  if (modeEl) modeEl.textContent = drawMode === \"MANUAL\" ? \"👤 دستی\" : drawMode === \"AUTO\" ? `🤖 خودکار • هر ${Number(data.interval_seconds || 0)} ثانیه` : \"انتخاب نشده\";\n  if (lockEl) lockEl.textContent = locked ? \"🔒 قفل‌شده تا پایان بازی\" : \"آزاد تا شروع بازی\";\n  if (commitmentEl) commitmentEl.textContent = data.sequence_commitment ? String(data.sequence_commitment).slice(0, 12) : \"-\";\n  if (manualBtn) manualBtn.textContent = drawMode === \"MANUAL\" ? \"✅ دستی انتخاب شد\" : \"👤 انتخاب دستی\";\n  if (autoBtn) autoBtn.textContent = drawMode === \"AUTO\" ? \"✅ خودکار انتخاب شد\" : \"🤖 انتخاب خودکار\";\n  if (remainingEl) remainingEl.textContent = drawMode === \"AUTO\" && Number.isFinite(Number(data.remaining_count)) ? String(Number(data.remaining_count)) : \"-\";\n  if (intervalEl && data.interval_seconds && document.activeElement !== intervalEl) {\n    intervalEl.value = String(data.interval_seconds);\n  }""",
    )

    replace_once(
        "backend/app/static/mini/app.js",
        """async function adminAutoDrawAction(action) {\n  const { gid } = requireAdminGameStatus([\"RUNNING\"], \"کنترل شماره‌خوان خودکار\");\n  const body = action === \"start\"\n    ? { interval_seconds: Number(getVal(\"adminAutoDrawInterval\") || 10) }\n    : undefined;\n  const actionText = { start: \"شروع\", pause: \"توقف موقت\", resume: \"ادامه\", stop: \"پایان\" }[action] || action;\n  setAdminLocalHint(\"adminAutoDrawHint\", `در حال ${actionText} شماره‌خوان...`);\n  const out = await apiFetch(`/mini-api/admin/games/${gid}/auto-draw/${action}`, {\n    method: \"POST\",\n    ...(body ? { body } : {}),\n  });\n  state.admin.autoDrawByGame.set(gid, out?.auto_draw || {});\n  renderAdminAutoDraw();\n  setAdminLocalHint(\"adminAutoDrawHint\", `${actionText} شماره‌خوان با موفقیت انجام شد.`, \"success\");\n  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid)]);\n}""",
        """async function adminSelectDrawMode(mode) {\n  const { gid } = requireAdminGameStatus([\"LOBBY\"], \"انتخاب روش شماره‌خوانی\");\n  const drawMode = String(mode || \"\").toUpperCase();\n  if (drawMode !== \"MANUAL\" && drawMode !== \"AUTO\") throw new Error(\"روش شماره‌خوانی نامعتبر است.\");\n  const body = {\n    draw_mode: drawMode,\n    interval_seconds: drawMode === \"AUTO\" ? Number(getVal(\"adminAutoDrawInterval\") || 10) : null,\n  };\n  setAdminLocalHint(\"adminAutoDrawHint\", drawMode === \"AUTO\" ? \"در حال آماده‌سازی ترتیب تصادفی و قفل امن...\" : \"در حال انتخاب حالت دستی...\");\n  const out = await apiFetch(`/mini-api/admin/games/${gid}/draw-mode`, { method: \"PUT\", body });\n  state.admin.autoDrawByGame.set(gid, out || {});\n  renderAdminAutoDraw();\n  setAdminLocalHint(\"adminAutoDrawHint\", drawMode === \"AUTO\" ? \"حالت خودکار آماده شد؛ با شروع بازی، ترتیب و فاصله قفل می‌شوند.\" : \"حالت دستی انتخاب شد؛ با شروع بازی این انتخاب قفل می‌شود.\", \"success\");\n  await refreshAdminGames();\n}\n\nasync function adminAutoDrawAction(action) {\n  const { gid } = requireAdminGameStatus([\"RUNNING\"], \"کنترل شماره‌خوان خودکار\");\n  if (action !== \"pause\" && action !== \"resume\") throw new Error(\"در بازی قفل‌شده فقط مکث یا ادامه مجاز است.\");\n  const actionText = action === \"pause\" ? \"مکث\" : \"ادامه\";\n  setAdminLocalHint(\"adminAutoDrawHint\", `در حال ${actionText} شماره‌خوان...`);\n  const out = await apiFetch(`/mini-api/admin/games/${gid}/auto-draw/${action}`, { method: \"POST\" });\n  state.admin.autoDrawByGame.set(gid, out?.auto_draw || {});\n  renderAdminAutoDraw();\n  setAdminLocalHint(\"adminAutoDrawHint\", action === \"pause\" ? \"شماره‌خوان مکث کرد؛ ترتیب قفل‌شده بدون تغییر باقی ماند.\" : \"شماره‌خوان از همان ترتیب قبلی ادامه پیدا کرد.\", \"success\");\n  await Promise.allSettled([refreshAdminGames(), openLiveGame(gid)]);\n}""",
    )

    replace_once(
        "backend/app/static/mini/app.js",
        """  bind(\"adminCallBtn\", \"click\", () => adminCallNumber().catch((e) => setAdminLocalError(\"adminCallActionHint\", e)));\n  bind(\"adminUndoBtn\", \"click\", () => adminUndoCall().catch((e) => setAdminLocalError(\"adminCallActionHint\", e)));\n  bind(\"adminAutoDrawStartBtn\", \"click\", () => adminAutoDrawAction(\"start\").catch((e) => setAdminLocalError(\"adminAutoDrawHint\", e)));\n  bind(\"adminAutoDrawPauseBtn\", \"click\", () => adminAutoDrawAction(\"pause\").catch((e) => setAdminLocalError(\"adminAutoDrawHint\", e)));\n  bind(\"adminAutoDrawResumeBtn\", \"click\", () => adminAutoDrawAction(\"resume\").catch((e) => setAdminLocalError(\"adminAutoDrawHint\", e)));\n  bind(\"adminAutoDrawStopBtn\", \"click\", () => adminAutoDrawAction(\"stop\").catch((e) => setAdminLocalError(\"adminAutoDrawHint\", e)));""",
        """  bind(\"adminCallBtn\", \"click\", () => adminCallNumber().catch((e) => setAdminLocalError(\"adminCallActionHint\", e)));\n  bind(\"adminUndoBtn\", \"click\", () => adminUndoCall().catch((e) => setAdminLocalError(\"adminCallActionHint\", e)));\n  bind(\"adminDrawModeManualBtn\", \"click\", () => adminSelectDrawMode(\"MANUAL\").catch((e) => setAdminLocalError(\"adminAutoDrawHint\", e)));\n  bind(\"adminDrawModeAutoBtn\", \"click\", () => adminSelectDrawMode(\"AUTO\").catch((e) => setAdminLocalError(\"adminAutoDrawHint\", e)));\n  bind(\"adminAutoDrawPauseBtn\", \"click\", () => adminAutoDrawAction(\"pause\").catch((e) => setAdminLocalError(\"adminAutoDrawHint\", e)));\n  bind(\"adminAutoDrawResumeBtn\", \"click\", () => adminAutoDrawAction(\"resume\").catch((e) => setAdminLocalError(\"adminAutoDrawHint\", e)));""",
    )

    print("mini locked draw UI patch complete")


if __name__ == "__main__":
    main()
