import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const mini = new URL("../../app/static/mini/", import.meta.url);
const js = readFileSync(new URL("app.js", mini), "utf8");
const html = readFileSync(new URL("index.html", mini), "utf8");
const css = readFileSync(new URL("ux-v2.css", mini), "utf8");
const botWallet = readFileSync(new URL("../../../davarna-bot/bot/routers/wallet.py", import.meta.url), "utf8");
const botUserKb = readFileSync(new URL("../../../davarna-bot/bot/keyboards/admin_users.py", import.meta.url), "utf8");
const miniRouter = readFileSync(new URL("../../app/routers/mini_router.py", import.meta.url), "utf8");
const financeRouter = readFileSync(new URL("../../app/routers/finance_router.py", import.meta.url), "utf8");
const settingsRouter = readFileSync(new URL("../../app/routers/settings_router.py", import.meta.url), "utf8");

for (const id of [
  "bankDepositModeBtn", "cryptoDepositModeBtn", "depositUnavailableNote",
  "adminUsersRecent", "superAdminFilterInput", "superAdminListRefreshBtn",
  "superAdminListSummary",
]) {
  assert.ok(html.includes('id="' + id + '"'), "Missing UI target: " + id);
}
assert.match(css, /\.admin-list-filter\s*\{/);
assert.match(css, /\.admin-quick-history\s*\{/);
assert.match(html, /app\.js\?v=payments-admin-wave1-20261106/);
assert.match(js, /function renderAdminUsersRecent\(/);
assert.match(js, /function renderSuperAdminList\(/);
assert.match(js, /function syncDepositMethodAvailability\(/);
assert.match(js, /super-admin-select/);
assert.match(js, /super-admin-profile/);
assert.match(js, /recentIds/);

const start = js.indexOf("function depositMethodAvailability()");
const end = js.indexOf("\nfunction renderCryptoHealthSummary", start);
assert.ok(start >= 0 && end > start, "payment controls not found");
const paymentFunctions = js.slice(start, end);
const elements = new Map();
const el = (id) => {
  if (!elements.has(id)) {
    elements.set(id, {
      disabled: false,
      classList: { values: new Map(), toggle(name, active) { this.values.set(name, active); } },
      setAttribute(name, value) { this[name] = value; },
      textContent: "",
      tabIndex: 0,
    });
  }
  return elements.get(id);
};
const tabs = [
  { ...el("bankDepositModeBtn"), getAttribute() { return "bank"; } },
  { ...el("cryptoDepositModeBtn"), getAttribute() { return "crypto"; } },
];
const context = {
  state: { depositDestinations: [], cryptoOptions: { enabled: false, options: [] } },
  document: {
    querySelectorAll() { return tabs; },
    querySelector() { return tabs.find((tab) => tab.classList.values.get("active")) || null; },
  },
  getEl: el,
};
vm.runInNewContext(paymentFunctions + "\nthis.syncPayments = syncDepositMethodAvailability;", context);
context.syncPayments();
assert.equal(el("bankDepositModeBtn").disabled, true);
assert.equal(el("cryptoDepositModeBtn").disabled, true);
assert.equal(el("depositUnavailableNote").classList.values.get("hidden"), false);

context.state.depositDestinations = [{ id: "active" }];
context.syncPayments();
assert.equal(el("bankDepositModeBtn").disabled, false);
assert.equal(el("cryptoDepositModeBtn").disabled, true);
assert.equal(el("bankDepositPanel").classList.values.get("hidden"), false);

context.state.depositDestinations = [];
context.state.cryptoOptions = { enabled: true, options: [{ network: "TON" }] };
context.syncPayments();
assert.equal(el("bankDepositModeBtn").disabled, true);
assert.equal(el("cryptoDepositModeBtn").disabled, false);
assert.equal(el("cryptoDepositPanel").classList.values.get("hidden"), false);

assert.match(botWallet, /if bank_enabled:/);
assert.match(botWallet, /if crypto_enabled:/);
assert.match(botWallet, /bot_list_deposit_destinations/);
assert.match(botWallet, /bot_crypto_options/);
assert.match(botUserKb, /restriction_active/);
assert.match(miniRouter, /if not _bank_deposit_enabled\(db\):/);
assert.match(financeRouter, /db\.get\(AppSetting, "bank_deposit_enabled"\)/);
assert.match(settingsRouter, /\{CRYPTO_RUNTIME_SETTING_KEY, "bank_deposit_enabled"\}/);

console.log("PASS: payment option visibility, legacy API guard and admin UX wiring.");
