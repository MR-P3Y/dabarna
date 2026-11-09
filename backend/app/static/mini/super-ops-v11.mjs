// Superadmin v1.1: read-only presentation of the existing ops-dashboard API.
// No financial writes, new endpoints, polling loop, or authorization shortcuts.

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[ch]));

export function safeCount(value) {
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? Math.trunc(n) : 0;
}

const countFa = (value) => safeCount(value).toLocaleString("fa-IR");
const moneyFa = (value) => countFa(value) + " تومان";

function gameStatus(raw) {
  if (raw === "RUNNING") return { text: "در حال اجرا", kind: "running" };
  if (raw === "LOBBY") return { text: "در انتظار شروع", kind: "lobby" };
  return { text: "وضعیت نامشخص", kind: "unknown" };
}

function serviceStatus(service) {
  // Bot is MONITORED / ok:null, not a verified healthy service.
  if (service?.ok === true) return { text: "سالم", kind: "healthy" };
  if (service?.ok === false) return { text: "خطا", kind: "error" };
  return { text: "در پایش مجزا", kind: "unknown" };
}

export function renderSuperOpsLayout(payload) {
  const counts = payload?.counts || {};
  const games = Array.isArray(payload?.active_games) ? payload.active_games.slice(0, 6) : [];
  const services = Array.isArray(payload?.system?.services) ? payload.system.services : [];
  const running = games.filter((game) => game?.status === "RUNNING").length;
  const lobby = games.filter((game) => game?.status === "LOBBY").length;
  const withdrawals = safeCount(counts.pending_withdraws) + safeCount(counts.approved_withdraws);

  const metrics = [
    ["بازی‌های نمایش‌داده‌شده", games.length, "حداکثر شش بازی فعال اخیر", "normal"],
    ["در حال اجرا", running, "در میان بازی‌های بالا", "normal"],
    ["منتظر شروع", lobby, "در میان بازی‌های بالا", "normal"],
    ["واریز در انتظار", counts.pending_deposits, "نیازمند بررسی مدیر مجاز", "attention"],
    ["برداشت در صف", withdrawals, "در انتظار و تأییدشده", "attention"],
    ["کریپتو نیازمند بررسی", counts.crypto_needs_review, "فقط شمارش، بدون جزئیات خصوصی", "attention"],
    ["هشدار ریسک ۲۴ ساعت", counts.risk_events_24h, "رویدادهای ثبت‌شده ریسک", "attention"],
  ];

  const metricsHtml = metrics.map(([title, amount, note, kind]) => `
    <div class="super-ops-metric ${kind === "attention" && safeCount(amount) > 0 ? "has-attention" : ""}">
      <span class="super-ops-metric-label">${escapeHtml(title)}</span>
      <strong class="super-ops-metric-value" dir="auto">${countFa(amount)}</strong>
      <small>${escapeHtml(note)}</small>
    </div>`).join("");

  const servicesHtml = services.length
    ? services.map((svc) => {
      const status = serviceStatus(svc);
      return `
        <div class="super-ops-service is-${status.kind}">
          <span class="super-ops-service-name">${escapeHtml(svc?.title || svc?.key || "سرویس")}</span>
          <strong>${escapeHtml(status.text)}</strong>
        </div>`;
    }).join("")
    : '<p class="super-ops-empty">وضعیت سرویس‌ها هنوز دریافت نشده است.</p>';

  const gamesHtml = games.length
    ? games.map((game) => {
      const id = safeCount(game?.id);
      const status = gameStatus(game?.status);
      return `
        <article class="super-ops-game">
          <div class="super-ops-game-top">
            <strong>بازی #${countFa(id)}</strong>
            <span class="super-ops-game-status is-${status.kind}">${status.text}</span>
          </div>
          <div class="super-ops-game-facts">
            <span>بازیکن <b>${countFa(game?.players_count)}</b></span>
            <span>کارت <b>${countFa(game?.cards_count)}</b></span>
            <span>اعداد خوانده‌شده <b>${countFa(game?.called_count)} / ۹۰</b></span>
          </div>
          <div class="super-ops-game-bottom">
            <span>مجموع جایزه <strong>${moneyFa(game?.prize_pool)}</strong></span>
            <button class="small-btn admin-ops-open-game" type="button"
              data-game-id="${id}" ${id ? "" : "disabled"}>مشاهده بازی</button>
          </div>
        </article>`;
    }).join("")
    : '<div class="super-ops-empty">بازی فعالی در فهرست دریافتی وجود ندارد.</div>';

  return `
    <section class="super-ops-metrics" aria-label="شاخص‌های عملیات">${metricsHtml}</section>
    <section class="super-ops-sections">
      <div class="super-ops-section">
        <div class="super-ops-section-heading">
          <h4>بازی‌های در جریان</h4>
          <span>داده واقعی API، حداکثر ۶ بازی</span>
        </div>
        <div class="super-ops-games">${gamesHtml}</div>
      </div>
      <div class="super-ops-section">
        <div class="super-ops-section-heading">
          <h4>سلامت سرویس‌ها</h4>
          <span>وضعیت Bot از مانیتور مستقل</span>
        </div>
        <div class="super-ops-services">${servicesHtml}</div>
        <p class="super-ops-footnote">این صفحه وضعیت سرویس‌ها را از API می‌خواند؛ نبود خطا به معنی تأیید تحویل همه پیام‌های تلگرام نیست.</p>
      </div>
    </section>`;
}
