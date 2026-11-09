import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const mini = join(here, "../../app/static/mini");
const html = readFileSync(join(mini, "index.html"), "utf8");
const source = readFileSync(join(mini, "app.js"), "utf8");
const css = readFileSync(join(mini, "ux-v2.css"), "utf8");

new vm.Script(source, { filename: "app.js" });
assert.match(html, /id="adminOpsHeading"/);
assert.match(html, /id="adminOpsStatus".*data-state="loading"/);
assert.match(html, /id="adminOpsUpdatedAt"/);
assert.match(html, /id="adminOpsDashboard"[^>]*aria-busy="true"/);
assert.match(html, /id="adminOpsSuperJump" class="hidden"/);
assert.match(html, /app\.js\?v=20261109-superadmin-dashboard-v11/);
assert.match(html, /ux-v2\.css\?v=20261109-superadmin-dashboard-v11/);
assert.match(source, /id === "superAdminSection" && !state\.admin\.canManageSuperSettings/);
assert.match(source, /document\.visibilityState === "hidden"/);
assert.match(source, /ADMIN_OPS_POLL_INTERVAL_MS = 45_000/);
assert.match(source, /\.\.\.\(!silent \? \[refreshAdminOpsDashboard\(\)\] : \[\]\)/, "global silent polling must not duplicate dashboard requests");
assert.match(source, /if \(adminOpsInFlight\) return adminOpsInFlight/);
assert.match(source, /stopAdminOpsAutoRefresh\(\)/);
assert.match(css, /prefers-reduced-motion: reduce/);
assert.match(css, /admin-ops-dashboard-v11/);

const start = source.indexOf("function adminServiceStatusClass(service) {");
const end = source.indexOf("\nfunction renderAdminAuditLogs(payload) {", start);
assert(start >= 0 && end > start, "extract read-only dashboard functions");
const snippet = source.slice(start, end);
assert(!/method:\s*["'](?:POST|PUT|DELETE)["']/i.test(snippet), "dashboard must remain read-only");

const dashboard = { innerHTML: "", attributes: {}, setAttribute(k, v) { this.attributes[k] = v; }, querySelectorAll() { return []; } };
const status = { textContent: "", dataset: {} };
const updated = { textContent: "" };
const elements = {
  adminOpsDashboard: dashboard,
  adminOpsStatus: status,
  adminOpsUpdatedAt: updated,
};
const payload = {
  counts: { pending_deposits: 2, pending_withdraws: 1, approved_withdraws: 3, crypto_needs_review: 0, risk_events_24h: 1 },
  system: { services: [{ key: "backend", title: "<img src=x onerror=alert(1)>", status: "OK", ok: true }] },
  active_games: [{ id: 101, status: "RUNNING", called_count: 4, players_count: 2, cards_count: 4, prize_pool: 10000 }],
};
const context = {
  state: { admin: { enabled: true } },
  getEl: (id) => elements[id] || null,
  toFaDigits: (value) => String(value),
  safeText: (value) => String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
  statusLabel: (value) => value,
  toman: (value) => String(value) + " تومان",
  apiFetch: async () => payload,
  Date,
  Number,
  setInterval,
  clearInterval,
};
vm.createContext(context);
vm.runInContext(snippet, context);
await vm.runInContext("refreshAdminOpsDashboard()", context);
assert.equal(status.dataset.state, "fresh");
assert.equal(dashboard.attributes["aria-busy"], "false");
assert.match(dashboard.innerHTML, /بازی فعال/);
assert.match(dashboard.innerHTML, /برداشت در صف/);
assert.match(dashboard.innerHTML, /&lt;img src=x onerror=alert\(1\)&gt;/);
assert.doesNotMatch(dashboard.innerHTML, /<img src=x onerror/);

// Regression: finance counters must disappear entirely (not become misleading zero cards)
// for ADMIN/GAME_OPERATOR when the API marks them as hidden.
context.renderAdminOpsDashboard({
  ...payload,
  finance_visible: false,
});
assert.match(dashboard.innerHTML, /بازی فعال/);
for (const label of ["واریز در انتظار", "برداشت در صف", "کریپتو نیازمند بررسی", "هشدار ریسک ۲۴ساعت"]) {
  assert.doesNotMatch(dashboard.innerHTML, new RegExp(label), "leaked restricted finance card: " + label);
}
context.renderAdminOpsDashboard({ ...payload, finance_visible: true });
assert.match(dashboard.innerHTML, /واریز در انتظار/);
assert.match(dashboard.innerHTML, /برداشت در صف/);

context.renderAdminOpsDashboard({
  counts: {}, active_games: [],
  system: { services: [{ title: "Telegram Bot", ok: null, status: "MONITORED" }] },
});
assert.match(dashboard.innerHTML, /در پایش سرور/, "MONITORED bot is not reported healthy");
await vm.runInContext("refreshAdminOpsDashboard()", context);
const snapshot = dashboard.innerHTML;
context.apiFetch = async () => { throw new Error("network offline"); };
await assert.rejects(vm.runInContext("refreshAdminOpsDashboard()", context), /network offline/);
assert.equal(status.dataset.state, "error");
assert.equal(dashboard.innerHTML, snapshot, "stale valid data survives a network error");
assert.equal(dashboard.attributes["aria-busy"], "false");
context.apiFetch = async () => payload;
await vm.runInContext("refreshAdminOpsDashboard()", context);
assert.equal(status.dataset.state, "fresh", "retry recovers after an error");

console.log("PASS: superadmin v1.1 dashboard contract, read-only render, XSS escaping, failure/retry and cache revision");
