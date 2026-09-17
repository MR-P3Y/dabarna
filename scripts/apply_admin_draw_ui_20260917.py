from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "backend/app/static/mini/index.html"
CSS = ROOT / "backend/app/static/mini/styles.css"
JS = ROOT / "backend/app/static/mini/app.js"

HTML_START = '                  <label id="adminCallLabel" for="adminCallNumberInput">عدد برای اعلام</label>'
HTML_END = '                  <div id="adminCallActionHint" class="step-hint action-local-hint"></div>'

NEW_HTML = '''                  <div id="adminDrawModeShell" class="admin-draw-shell">
                    <div class="admin-draw-step-head">
                      <span class="admin-draw-step-no">۱</span>
                      <div>
                        <strong>روش شماره‌خوانی</strong>
                        <small>قبل از شروع بازی، یکی از دو روش را انتخاب کنید.</small>
                      </div>
                    </div>

                    <div class="admin-draw-mode-grid">
                      <button id="adminDrawModeManualBtn" class="admin-draw-mode-card" type="button">
                        <span class="admin-draw-mode-icon">👤</span>
                        <span class="admin-draw-mode-copy">
                          <strong>دستی</strong>
                          <small>اعداد را ادمین اعلام می‌کند</small>
                        </span>
                        <span class="admin-draw-mode-state">انتخاب</span>
                      </button>

                      <button id="adminDrawModeAutoBtn" class="admin-draw-mode-card" type="button">
                        <span class="admin-draw-mode-icon">🤖</span>
                        <span class="admin-draw-mode-copy">
                          <strong>خودکار</strong>
                          <small>اعلام خودکار با ترتیب ثابت و قفل‌شده</small>
                        </span>
                        <span class="admin-draw-mode-state">انتخاب</span>
                      </button>
                    </div>

                    <div class="admin-draw-selection-summary">
                      <div>
                        <span>روش فعلی</span>
                        <strong id="adminDrawModeLabel">انتخاب نشده</strong>
                      </div>
                      <div>
                        <span>وضعیت انتخاب</span>
                        <strong id="adminDrawModeLock">آزاد تا شروع بازی</strong>
                      </div>
                    </div>

                    <div id="adminDrawModeEmpty" class="admin-draw-empty-state">
                      <strong>هنوز روشی انتخاب نشده</strong>
                      <span>برای فعال‌شدن شروع بازی، ابتدا دستی یا خودکار را انتخاب کنید.</span>
                    </div>

                    <div id="adminManualDrawPanel" class="admin-draw-config-panel hidden">
                      <div class="admin-draw-step-head compact">
                        <span class="admin-draw-step-no">۲</span>
                        <div>
                          <strong>کنترل دستی</strong>
                          <small>پس از شروع بازی، عدد را وارد کنید یا از صفحه‌کلید استفاده کنید.</small>
                        </div>
                      </div>

                      <label id="adminCallLabel" for="adminCallNumberInput">عدد برای اعلام</label>
                      <input id="adminCallNumberInput" type="tel" inputmode="numeric" pattern="[0-9]*" min="1" max="90" maxlength="2" enterkeyhint="done" autocomplete="off" />

                      <div class="admin-action-row">
                        <button id="adminCallBtn" class="small-btn primary" type="button">اعلام عدد</button>
                        <button id="adminUndoBtn" class="small-btn" type="button">حذف آخرین عدد</button>
                      </div>

                      <div id="adminCallQuickPanel" class="admin-call-quick-panel">
                        <div class="admin-call-mini-stats">
                          <div>
                            <span>آخرین عدد</span>
                            <strong id="adminCallLastNumber">-</strong>
                          </div>
                          <div>
                            <span>۴ عدد اخیر</span>
                            <strong id="adminCallRecentNumbers">-</strong>
                          </div>
                          <div>
                            <span>پیشرفت</span>
                            <strong id="adminCallProgressCount">0/90</strong>
                          </div>
                        </div>
                        <div id="adminCallKeypad" class="admin-call-keypad" aria-label="Admin number keypad">
                          <button type="button" data-admin-call-digit="1">1</button>
                          <button type="button" data-admin-call-digit="2">2</button>
                          <button type="button" data-admin-call-digit="3">3</button>
                          <button type="button" data-admin-call-digit="4">4</button>
                          <button type="button" data-admin-call-digit="5">5</button>
                          <button type="button" data-admin-call-digit="6">6</button>
                          <button type="button" data-admin-call-digit="7">7</button>
                          <button type="button" data-admin-call-digit="8">8</button>
                          <button type="button" data-admin-call-digit="9">9</button>
                          <button type="button" class="soft" data-admin-call-clear="1">پاک</button>
                          <button type="button" data-admin-call-digit="0">0</button>
                          <button type="button" class="soft" data-admin-call-backspace="1">&#9003;</button>
                        </div>
                      </div>
                      <div id="adminCallActionHint" class="step-hint action-local-hint"></div>
                    </div>

                    <div id="adminAutoDrawPanel" class="admin-auto-draw-panel admin-draw-config-panel hidden">
                      <div class="admin-draw-step-head compact">
                        <span class="admin-draw-step-no">۲</span>
                        <div>
                          <strong>تنظیمات خودکار</strong>
                          <small>سرعت را انتخاب کنید؛ با شروع بازی ترتیب و فاصله قفل می‌شوند.</small>
                        </div>
                      </div>

                      <label for="adminAutoDrawInterval">فاصله اعلام خودکار</label>
                      <select id="adminAutoDrawInterval" class="admin-draw-native-select">
                        <option value="5">۵ ثانیه</option>
                        <option value="8">۸ ثانیه</option>
                        <option value="10" selected>۱۰ ثانیه</option>
                        <option value="15">۱۵ ثانیه</option>
                      </select>

                      <div id="adminAutoDrawIntervalChips" class="admin-draw-interval-grid">
                        <button type="button" data-admin-auto-interval="5">۵ ثانیه</button>
                        <button type="button" data-admin-auto-interval="8">۸ ثانیه</button>
                        <button type="button" data-admin-auto-interval="10">۱۰ ثانیه</button>
                        <button type="button" data-admin-auto-interval="15">۱۵ ثانیه</button>
                      </div>

                      <div class="admin-auto-draw-head">
                        <div>
                          <span>وضعیت</span>
                          <strong id="adminAutoDrawStatus">متوقف</strong>
                        </div>
                        <div>
                          <span>عدد بعدی تا</span>
                          <strong id="adminAutoDrawCountdown">--:--</strong>
                        </div>
                        <div>
                          <span>اعداد باقی‌مانده</span>
                          <strong id="adminAutoDrawRemaining">-</strong>
                        </div>
                      </div>

                      <div class="admin-draw-proof">
                        <span>شناسه ترتیب ثابت</span>
                        <strong id="adminDrawCommitment">-</strong>
                      </div>

                      <div class="admin-action-row">
                        <button id="adminAutoDrawPauseBtn" class="small-btn" type="button">⏸ مکث</button>
                        <button id="adminAutoDrawResumeBtn" class="small-btn primary" type="button">▶️ ادامه همان ترتیب</button>
                      </div>
                      <div id="adminAutoDrawHint" class="step-hint action-local-hint">روش شماره‌خوانی را قبل از شروع بازی انتخاب کنید.</div>
                    </div>

                    <div id="adminDrawStartPanel" class="admin-draw-start-panel">
                      <div class="admin-draw-step-head compact">
                        <span class="admin-draw-step-no">۳</span>
                        <div>
                          <strong>شروع بازی</strong>
                          <small id="adminDrawStartSummary">ابتدا روش شماره‌خوانی را انتخاب کنید.</small>
                        </div>
                      </div>
                      <button id="adminStartBtn" class="small-btn primary admin-draw-start-btn" type="button">شروع بازی</button>
                    </div>
                  </div>'''

CSS_MARKER_START = "/* ADMIN_DRAW_UI_20260917_START */"
CSS_MARKER_END = "/* ADMIN_DRAW_UI_20260917_END */"
NEW_CSS = r'''
/* ADMIN_DRAW_UI_20260917_START */
.admin-draw-shell {
  display: grid;
  gap: 14px;
  padding: 14px;
  border: 1px solid rgba(122, 155, 255, 0.18);
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(15, 28, 57, 0.92), rgba(8, 18, 39, 0.96));
}

.admin-draw-step-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.admin-draw-step-head.compact {
  align-items: flex-start;
}

.admin-draw-step-head > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.admin-draw-step-head strong {
  color: #f4f7ff;
  font-size: 13px;
}

.admin-draw-step-head small {
  color: #9eacc9;
  font-size: 10px;
  line-height: 1.8;
}

.admin-draw-step-no {
  display: grid;
  place-items: center;
  flex: 0 0 30px;
  width: 30px;
  height: 30px;
  border-radius: 10px;
  background: rgba(91, 194, 225, 0.13);
  border: 1px solid rgba(91, 194, 225, 0.34);
  color: #bfefff;
  font-weight: 800;
}

.admin-draw-mode-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.admin-draw-mode-card {
  position: relative;
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  min-height: 94px;
  padding: 12px;
  text-align: right;
  border: 1px solid rgba(125, 160, 245, 0.22);
  border-radius: 14px;
  background: rgba(10, 23, 48, 0.8);
  color: #f4f7ff;
  cursor: pointer;
  transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease, opacity 0.18s ease;
}

.admin-draw-mode-card:not(:disabled):active {
  transform: scale(0.985);
}

.admin-draw-mode-card.is-selected {
  border-color: rgba(91, 194, 225, 0.72);
  background: linear-gradient(145deg, rgba(32, 70, 115, 0.88), rgba(13, 37, 69, 0.96));
  box-shadow: 0 0 0 1px rgba(91, 194, 225, 0.12) inset, 0 10px 28px rgba(2, 10, 26, 0.28);
}

.admin-draw-mode-card.is-inactive {
  opacity: 0.5;
}

.admin-draw-mode-card.is-selected.is-inactive {
  opacity: 1;
}

.admin-draw-mode-card:disabled {
  cursor: default;
}

.admin-draw-mode-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.055);
  font-size: 20px;
}

.admin-draw-mode-copy {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.admin-draw-mode-copy strong {
  font-size: 13px;
}

.admin-draw-mode-copy small {
  color: #9eacc9;
  font-size: 9px;
  line-height: 1.7;
}

.admin-draw-mode-state {
  position: absolute;
  inset-inline-end: 9px;
  top: 8px;
  padding: 3px 7px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  color: #aebbd6;
  font-size: 8px;
  font-weight: 700;
}

.admin-draw-mode-card.is-selected .admin-draw-mode-state {
  background: rgba(91, 194, 225, 0.15);
  color: #c9f3ff;
}

.admin-draw-selection-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.admin-draw-selection-summary > div,
.admin-draw-proof {
  display: grid;
  gap: 4px;
  padding: 10px 11px;
  border: 1px solid rgba(125, 160, 245, 0.15);
  border-radius: 11px;
  background: rgba(6, 15, 34, 0.56);
}

.admin-draw-selection-summary span,
.admin-draw-proof span {
  color: #8f9fbd;
  font-size: 9px;
}

.admin-draw-selection-summary strong,
.admin-draw-proof strong {
  color: #eef4ff;
  font-size: 10px;
  overflow-wrap: anywhere;
}

.admin-draw-empty-state {
  display: grid;
  gap: 5px;
  padding: 13px;
  border: 1px dashed rgba(125, 160, 245, 0.28);
  border-radius: 12px;
  text-align: center;
  background: rgba(6, 15, 34, 0.36);
}

.admin-draw-empty-state strong {
  color: #e9efff;
  font-size: 11px;
}

.admin-draw-empty-state span {
  color: #8f9fbd;
  font-size: 9px;
  line-height: 1.7;
}

.admin-draw-config-panel {
  display: grid;
  gap: 11px;
  padding: 13px;
  border: 1px solid rgba(125, 160, 245, 0.16);
  border-radius: 13px;
  background: rgba(6, 15, 34, 0.48);
}

.admin-draw-native-select {
  display: none !important;
}

.admin-draw-interval-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 7px;
}

.admin-draw-interval-grid button {
  min-height: 38px;
  padding: 7px 4px;
  border: 1px solid rgba(125, 160, 245, 0.2);
  border-radius: 10px;
  background: rgba(13, 30, 61, 0.9);
  color: #c6d0e6;
  font: inherit;
  font-size: 9px;
}

.admin-draw-interval-grid button.is-selected {
  border-color: rgba(91, 194, 225, 0.68);
  background: rgba(40, 93, 137, 0.52);
  color: #eafaff;
  font-weight: 800;
}

.admin-draw-interval-grid button:disabled {
  opacity: 0.58;
}

.admin-draw-start-panel {
  display: grid;
  gap: 10px;
  padding-top: 12px;
  border-top: 1px solid rgba(125, 160, 245, 0.15);
}

.admin-draw-start-panel.is-complete .admin-draw-step-no {
  background: rgba(90, 190, 130, 0.12);
  border-color: rgba(90, 190, 130, 0.32);
}

.admin-draw-start-btn {
  width: 100%;
  min-height: 44px;
  font-weight: 800;
}

.admin-draw-shell.is-locked .admin-draw-mode-grid {
  opacity: 0.86;
}

@media (max-width: 410px) {
  .admin-draw-mode-grid,
  .admin-draw-selection-summary {
    grid-template-columns: 1fr;
  }

  .admin-draw-interval-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
/* ADMIN_DRAW_UI_20260917_END */
'''

NEW_RENDER = r'''function renderAdminAutoDraw() {
  const gid = Number(state.admin?.selectedGameId || 0);
  const data = adminAutoDrawState(gid) || {};
  const game = gid ? getAdminGameById(gid) : null;
  const gameStatus = String(game?.status || "").toUpperCase();
  const status = String(data.auto_status || data.status || "STOPPED").toUpperCase();
  const drawMode = String(data.draw_mode || "").toUpperCase();
  const locked = Boolean(data.locked);
  const isLobby = gameStatus === "LOBBY";
  const isRunning = gameStatus === "RUNNING";
  const validMode = drawMode === "MANUAL" || drawMode === "AUTO";
  const interval = Number(data.interval_seconds || getVal("adminAutoDrawInterval") || 10);
  const labels = { ARMED: "آماده شروع", RUNNING: "در حال اجرا", PAUSED: "متوقف موقت", STOPPED: "متوقف" };

  const shell = getEl("adminDrawModeShell");
  const emptyEl = getEl("adminDrawModeEmpty");
  const manualPanel = getEl("adminManualDrawPanel");
  const autoPanel = getEl("adminAutoDrawPanel");
  const startPanel = getEl("adminDrawStartPanel");
  const startSummary = getEl("adminDrawStartSummary");
  const startBtn = getEl("adminStartBtn");
  const statusEl = getEl("adminAutoDrawStatus");
  const remainingEl = getEl("adminAutoDrawRemaining");
  const countdownEl = getEl("adminAutoDrawCountdown");
  const intervalEl = getEl("adminAutoDrawInterval");
  const modeEl = getEl("adminDrawModeLabel");
  const lockEl = getEl("adminDrawModeLock");
  const commitmentEl = getEl("adminDrawCommitment");
  const manualBtn = getEl("adminDrawModeManualBtn");
  const autoBtn = getEl("adminDrawModeAutoBtn");

  if (shell) shell.classList.toggle("is-locked", locked || isRunning);
  if (emptyEl) emptyEl.classList.toggle("hidden", validMode);
  if (manualPanel) manualPanel.classList.toggle("hidden", drawMode !== "MANUAL");
  if (autoPanel) autoPanel.classList.toggle("hidden", drawMode !== "AUTO");
  if (startPanel) startPanel.classList.toggle("is-complete", isRunning || gameStatus === "ENDED");

  const paintModeCard = (btn, selected) => {
    if (!btn) return;
    btn.classList.toggle("is-selected", selected);
    btn.classList.toggle("is-inactive", validMode && !selected);
    const stateEl = btn.querySelector(".admin-draw-mode-state");
    if (stateEl) {
      stateEl.textContent = selected ? (locked || isRunning ? "🔒 قفل" : "✓ انتخاب‌شده") : (locked || isRunning ? "بسته" : "انتخاب");
    }
  };
  paintModeCard(manualBtn, drawMode === "MANUAL");
  paintModeCard(autoBtn, drawMode === "AUTO");

  if (statusEl) statusEl.textContent = drawMode === "MANUAL" ? "دستی" : (labels[status] || status);
  if (modeEl) modeEl.textContent = drawMode === "MANUAL" ? "👤 دستی" : drawMode === "AUTO" ? `🤖 خودکار • هر ${interval} ثانیه` : "انتخاب نشده";
  if (lockEl) lockEl.textContent = locked || isRunning ? "🔒 قفل‌شده تا پایان بازی" : "آزاد تا شروع بازی";
  if (commitmentEl) commitmentEl.textContent = data.sequence_commitment ? String(data.sequence_commitment).slice(0, 12) : "-";
  if (remainingEl) remainingEl.textContent = drawMode === "AUTO" && Number.isFinite(Number(data.remaining_count)) ? String(Number(data.remaining_count)) : "-";

  if (intervalEl && Number.isFinite(interval) && document.activeElement !== intervalEl) {
    intervalEl.value = String(interval);
  }

  document.querySelectorAll("[data-admin-auto-interval]").forEach((chip) => {
    const value = Number(chip.dataset.adminAutoInterval || 0);
    const selected = value === interval;
    const canChange = Boolean(gid && isLobby && !locked && drawMode === "AUTO");
    chip.classList.toggle("is-selected", selected);
    chip.disabled = !canChange;
    chip.onclick = () => {
      if (!canChange || !intervalEl) return;
      intervalEl.value = String(value);
      adminSelectDrawMode("AUTO").catch((e) => setAdminLocalError("adminAutoDrawHint", e));
    };
  });

  if (startSummary) {
    if (!gid) startSummary.textContent = "ابتدا یک بازی را برای مدیریت انتخاب کنید.";
    else if (!validMode) startSummary.textContent = "ابتدا روش شماره‌خوانی را انتخاب کنید.";
    else if (isLobby && drawMode === "MANUAL") startSummary.textContent = "آماده شروع با شماره‌خوانی دستی؛ پس از شروع روش قفل می‌شود.";
    else if (isLobby && drawMode === "AUTO") startSummary.textContent = `آماده شروع خودکار؛ اعلام هر ${interval} ثانیه و سپس قفل کامل.`;
    else if (isRunning && drawMode === "MANUAL") startSummary.textContent = "بازی در حالت دستی در حال اجراست و روش قفل شده است.";
    else if (isRunning && drawMode === "AUTO") startSummary.textContent = `بازی خودکار هر ${interval} ثانیه در حال اجراست؛ ترتیب ثابت است.`;
    else startSummary.textContent = "وضعیت بازی اجازه شروع دوباره نمی‌دهد.";
  }

  if (startBtn) {
    if (isLobby && drawMode === "MANUAL") startBtn.textContent = "شروع بازی با شماره‌خوانی دستی";
    else if (isLobby && drawMode === "AUTO") startBtn.textContent = "شروع بازی با شماره‌خوانی خودکار";
    else if (isRunning) startBtn.textContent = "🔒 بازی شروع شده";
    else startBtn.textContent = "شروع بازی";
  }

  if (countdownEl) {
    if (status !== "RUNNING" || !data.next_draw_at) {
      countdownEl.textContent = "--:--";
    } else {
      const remainingMs = Math.max(0, new Date(data.next_draw_at).getTime() - Date.now());
      const seconds = Math.ceil(remainingMs / 1000);
      countdownEl.textContent = `00:${String(seconds).padStart(2, "0")}`;
    }
  }

  updateAdminActionButtons();
}
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def replace_range(text: str, start_marker: str, end_marker: str, replacement: str, label: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise SystemExit(f"{label}: start marker not found")
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit(f"{label}: end marker not found")
    end += len(end_marker)
    return text[:start] + replacement + text[end:]


index = INDEX.read_text(encoding="utf-8")
if 'id="adminDrawModeShell"' not in index:
    index = replace_range(index, HTML_START, HTML_END, NEW_HTML, "index draw block")
index = re.sub(r'\.\/styles\.css\?v=[^"\']+', './styles.css?v=admin-draw-ui-20260917-1', index, count=1)
index = re.sub(r'\.\/app\.js\?v=[^"\']+', './app.js?v=admin-draw-ui-20260917-1', index, count=1)
INDEX.write_text(index, encoding="utf-8")

css = CSS.read_text(encoding="utf-8")
if CSS_MARKER_START in css:
    css = replace_range(css, CSS_MARKER_START, CSS_MARKER_END, NEW_CSS.strip(), "css admin draw block")
else:
    css = css.rstrip() + "\n\n" + NEW_CSS.strip() + "\n"
CSS.write_text(css, encoding="utf-8")

js = JS.read_text(encoding="utf-8")
render_start = js.find("function renderAdminAutoDraw() {")
render_end = js.find("async function refreshAdminAutoDraw", render_start)
if render_start < 0 or render_end < 0:
    raise SystemExit("app.js: renderAdminAutoDraw boundaries not found")
js = js[:render_start] + NEW_RENDER + "\n" + js[render_end:]
JS.write_text(js, encoding="utf-8")

# Structural safety checks.
final_index = INDEX.read_text(encoding="utf-8")
for element_id in (
    "adminDrawModeShell", "adminDrawModeManualBtn", "adminDrawModeAutoBtn",
    "adminManualDrawPanel", "adminAutoDrawPanel", "adminAutoDrawInterval",
    "adminCallNumberInput", "adminCallBtn", "adminUndoBtn", "adminStartBtn",
    "adminAutoDrawPauseBtn", "adminAutoDrawResumeBtn", "adminDrawCommitment",
):
    hits = final_index.count(f'id="{element_id}"')
    if hits != 1:
        raise SystemExit(f"duplicate/missing id {element_id}: {hits}")

print("ADMIN_DRAW_UI_PATCH_APPLIED")
