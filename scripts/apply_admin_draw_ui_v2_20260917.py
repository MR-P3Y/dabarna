from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "backend/app/static/mini/index.html"
CSS = ROOT / "backend/app/static/mini/styles.css"
JS = ROOT / "backend/app/static/mini/app.js"

html = HTML.read_text(encoding="utf-8")
css = CSS.read_text(encoding="utf-8")
js = JS.read_text(encoding="utf-8")

start = "/* ADMIN_DRAW_UI_20260917_START */"
end = "/* ADMIN_DRAW_UI_20260917_END */"
a = css.find(start)
b = css.find(end)
if a < 0 or b < 0 or b < a:
    raise SystemExit("admin draw css block not found")
b += len(end)

new_css = r'''/* ADMIN_DRAW_UI_20260917_START */
.admin-draw-shell {
  --draw-panel: rgba(8, 16, 34, 0.74);
  --draw-surface: rgba(255, 255, 255, 0.035);
  --draw-surface-strong: rgba(255, 255, 255, 0.055);
  --draw-border: rgba(125, 160, 245, 0.18);
  --draw-selected: rgba(95, 200, 255, 0.10);
  --draw-selected-border: rgba(95, 200, 255, 0.46);
  --draw-selected-text: #dff7ff;
  --draw-shadow: 0 10px 28px rgba(2, 8, 24, 0.22);
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--draw-border);
  border-radius: 14px;
  background: var(--draw-panel);
  box-shadow: var(--draw-shadow);
}

html[data-theme="light"] .admin-draw-shell {
  --draw-panel: rgba(255, 255, 255, 0.94);
  --draw-surface: #f8faff;
  --draw-surface-strong: #f1f5fb;
  --draw-border: rgba(28, 50, 92, 0.15);
  --draw-selected: rgba(23, 63, 189, 0.075);
  --draw-selected-border: rgba(23, 63, 189, 0.34);
  --draw-selected-text: #173fbd;
  --draw-shadow: 0 8px 24px rgba(31, 49, 84, 0.08);
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
  gap: 2px;
  min-width: 0;
}

.admin-draw-step-head strong {
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
}

.admin-draw-step-head small {
  color: var(--muted);
  font-size: 10px;
  line-height: 1.7;
}

.admin-draw-step-no {
  display: grid;
  place-items: center;
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--draw-surface-strong);
  border: 1px solid var(--draw-border);
  color: var(--accent);
  font-size: 11px;
  font-weight: 800;
}

.admin-draw-mode-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
}

.admin-draw-mode-card {
  position: relative;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  align-items: center;
  gap: 9px;
  min-height: 82px;
  padding: 11px;
  text-align: right;
  border: 1px solid var(--draw-border);
  border-radius: 11px;
  background: var(--draw-surface);
  color: var(--text);
  cursor: pointer;
  box-shadow: none;
  transition: border-color 0.16s ease, background 0.16s ease, opacity 0.16s ease, transform 0.16s ease;
}

.admin-draw-mode-card:not(:disabled):active {
  transform: scale(0.99);
}

.admin-draw-mode-card.is-selected {
  border-color: var(--draw-selected-border);
  background: var(--draw-selected);
}

.admin-draw-mode-card.is-inactive {
  opacity: 0.48;
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
  width: 34px;
  height: 34px;
  border-radius: 9px;
  border: 1px solid var(--draw-border);
  background: var(--draw-surface-strong);
  color: var(--accent);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.04em;
}

.admin-draw-mode-copy {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.admin-draw-mode-copy strong {
  color: var(--text);
  font-size: 12px;
  font-weight: 700;
}

.admin-draw-mode-copy small {
  color: var(--muted);
  font-size: 9px;
  line-height: 1.55;
}

.admin-draw-mode-state {
  position: absolute;
  inset-inline-end: 8px;
  top: 7px;
  padding: 2px 6px;
  border-radius: 6px;
  background: var(--draw-surface-strong);
  color: var(--muted);
  font-size: 8px;
  font-weight: 700;
}

.admin-draw-mode-card.is-selected .admin-draw-mode-state {
  color: var(--draw-selected-text);
  background: transparent;
}

.admin-draw-selection-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.admin-draw-selection-summary > div,
.admin-draw-proof {
  display: grid;
  gap: 3px;
  padding: 9px 10px;
  border: 1px solid var(--draw-border);
  border-radius: 9px;
  background: var(--draw-surface);
}

.admin-draw-selection-summary span,
.admin-draw-proof span {
  color: var(--muted);
  font-size: 9px;
}

.admin-draw-selection-summary strong,
.admin-draw-proof strong {
  color: var(--text);
  font-size: 10px;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.admin-draw-empty-state {
  display: grid;
  gap: 4px;
  padding: 11px;
  border: 1px dashed var(--draw-border);
  border-radius: 10px;
  text-align: center;
  background: var(--draw-surface);
}

.admin-draw-empty-state strong {
  color: var(--text);
  font-size: 10px;
}

.admin-draw-empty-state span {
  color: var(--muted);
  font-size: 9px;
  line-height: 1.6;
}

.admin-draw-config-panel {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--draw-border);
  border-radius: 10px;
  background: var(--draw-surface);
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
  min-height: 36px;
  padding: 6px 4px;
  border: 1px solid var(--draw-border);
  border-radius: 8px;
  background: var(--draw-surface-strong);
  color: var(--text);
  font: inherit;
  font-size: 9px;
  cursor: pointer;
}

.admin-draw-interval-grid button.is-selected {
  border-color: var(--draw-selected-border);
  background: var(--draw-selected);
  color: var(--draw-selected-text);
  font-weight: 800;
}

.admin-draw-interval-grid button:disabled {
  opacity: 0.52;
  cursor: default;
}

.admin-draw-start-panel {
  display: grid;
  gap: 9px;
  padding-top: 11px;
  border-top: 1px solid var(--draw-border);
}

.admin-draw-start-panel.is-complete .admin-draw-step-no {
  color: var(--success);
  border-color: rgba(105, 240, 192, 0.28);
}

html[data-theme="light"] .admin-draw-start-panel.is-complete .admin-draw-step-no {
  border-color: rgba(8, 112, 85, 0.24);
}

.admin-draw-start-btn {
  width: 100%;
  min-height: 42px;
  font-weight: 800;
}

.admin-draw-shell.is-locked .admin-draw-mode-grid {
  opacity: 0.84;
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
/* ADMIN_DRAW_UI_20260917_END */'''

css = css[:a] + new_css + css[b:]

html_replacements = {
    './styles.css?v=admin-draw-ui-20260917-1': './styles.css?v=admin-draw-ui-20260917-2',
    './app.js?v=admin-draw-ui-20260917-1': './app.js?v=admin-draw-ui-20260917-2',
    '<strong>روش شماره‌خوانی</strong>': '<strong>حالت شماره‌خوانی</strong>',
    '<small>قبل از شروع بازی، یکی از دو روش را انتخاب کنید.</small>': '<small>حالت اجرای بازی را انتخاب کنید.</small>',
    '<span class="admin-draw-mode-icon">👤</span>': '<span class="admin-draw-mode-icon">M</span>',
    '<small>اعداد را ادمین اعلام می‌کند</small>': '<small>اعلام عدد توسط ادمین</small>',
    '<span class="admin-draw-mode-icon">🤖</span>': '<span class="admin-draw-mode-icon">A</span>',
    '<small>اعلام خودکار با ترتیب ثابت و قفل‌شده</small>': '<small>اعلام خودکار با فاصله زمانی مشخص</small>',
    '<span>روش فعلی</span>': '<span>حالت</span>',
    '<span>وضعیت انتخاب</span>': '<span>وضعیت</span>',
    '<strong>هنوز روشی انتخاب نشده</strong>': '<strong>یک حالت انتخاب کنید</strong>',
    '<span>برای فعال‌شدن شروع بازی، ابتدا دستی یا خودکار را انتخاب کنید.</span>': '<span>برای ادامه، دستی یا خودکار را انتخاب کنید.</span>',
    '<strong>کنترل دستی</strong>': '<strong>شماره‌خوانی دستی</strong>',
    '<small>پس از شروع بازی، عدد را وارد کنید یا از صفحه‌کلید استفاده کنید.</small>': '<small>عدد را وارد و اعلام کنید.</small>',
    '<strong>تنظیمات خودکار</strong>': '<strong>شماره‌خوانی خودکار</strong>',
    '<small>سرعت را انتخاب کنید؛ با شروع بازی ترتیب و فاصله قفل می‌شوند.</small>': '<small>فاصله زمانی اعلام اعداد را تعیین کنید.</small>',
    '<label for="adminAutoDrawInterval">فاصله اعلام خودکار</label>': '<label for="adminAutoDrawInterval">فاصله اعلام</label>',
    '<span>شناسه ترتیب ثابت</span>': '<span>کد ترتیب</span>',
    '<button id="adminAutoDrawResumeBtn" class="small-btn primary" type="button">▶️ ادامه همان ترتیب</button>': '<button id="adminAutoDrawResumeBtn" class="small-btn primary" type="button">ادامه</button>',
    '<button id="adminAutoDrawPauseBtn" class="small-btn" type="button">⏸ مکث</button>': '<button id="adminAutoDrawPauseBtn" class="small-btn" type="button">مکث</button>',
    '<strong>شروع بازی</strong>': '<strong>شروع</strong>',
}
for old, new in html_replacements.items():
    if old not in html:
        raise SystemExit(f"html marker missing: {old}")
    html = html.replace(old, new, 1)

js_replacements = {
    'stateEl.textContent = selected ? (locked || isRunning ? "🔒 قفل" : "✓ انتخاب‌شده") : (locked || isRunning ? "بسته" : "انتخاب");': 'stateEl.textContent = selected ? (locked || isRunning ? "قفل‌شده" : "انتخاب‌شده") : (locked || isRunning ? "غیرفعال" : "انتخاب");',
    'if (modeEl) modeEl.textContent = drawMode === "MANUAL" ? "👤 دستی" : drawMode === "AUTO" ? `🤖 خودکار • هر ${interval} ثانیه` : "انتخاب نشده";': 'if (modeEl) modeEl.textContent = drawMode === "MANUAL" ? "دستی" : drawMode === "AUTO" ? `خودکار · ${interval} ثانیه` : "انتخاب نشده";',
    'if (lockEl) lockEl.textContent = locked || isRunning ? "🔒 قفل‌شده تا پایان بازی" : "آزاد تا شروع بازی";': 'if (lockEl) lockEl.textContent = locked || isRunning ? "قفل تا پایان بازی" : "قابل تغییر";',
    'else if (isLobby && drawMode === "MANUAL") startSummary.textContent = "آماده شروع با شماره‌خوانی دستی؛ پس از شروع روش قفل می‌شود.";': 'else if (isLobby && drawMode === "MANUAL") startSummary.textContent = "حالت دستی آماده شروع است.";',
    'else if (isLobby && drawMode === "AUTO") startSummary.textContent = `آماده شروع خودکار؛ اعلام هر ${interval} ثانیه و سپس قفل کامل.`;': 'else if (isLobby && drawMode === "AUTO") startSummary.textContent = `حالت خودکار با فاصله ${interval} ثانیه آماده شروع است.`;',
    'else if (isRunning && drawMode === "MANUAL") startSummary.textContent = "بازی در حالت دستی در حال اجراست و روش قفل شده است.";': 'else if (isRunning && drawMode === "MANUAL") startSummary.textContent = "بازی در حالت دستی در حال اجراست.";',
    'else if (isRunning && drawMode === "AUTO") startSummary.textContent = `بازی خودکار هر ${interval} ثانیه در حال اجراست؛ ترتیب ثابت است.`;': 'else if (isRunning && drawMode === "AUTO") startSummary.textContent = `بازی خودکار با فاصله ${interval} ثانیه در حال اجراست.`;',
    'if (isLobby && drawMode === "MANUAL") startBtn.textContent = "شروع بازی با شماره‌خوانی دستی";': 'if (isLobby && drawMode === "MANUAL") startBtn.textContent = "شروع بازی · دستی";',
    'else if (isLobby && drawMode === "AUTO") startBtn.textContent = "شروع بازی با شماره‌خوانی خودکار";': 'else if (isLobby && drawMode === "AUTO") startBtn.textContent = "شروع بازی · خودکار";',
    'else if (isRunning) startBtn.textContent = "🔒 بازی شروع شده";': 'else if (isRunning) startBtn.textContent = "بازی در حال اجرا";',
}
for old, new in js_replacements.items():
    if old not in js:
        raise SystemExit(f"js marker missing: {old}")
    js = js.replace(old, new, 1)

HTML.write_text(html, encoding="utf-8")
CSS.write_text(css, encoding="utf-8")
JS.write_text(js, encoding="utf-8")
print("ADMIN_DRAW_UI_V2_APPLIED")
