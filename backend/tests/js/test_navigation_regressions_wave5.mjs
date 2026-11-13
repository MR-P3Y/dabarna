import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const js = readFileSync(new URL("../../app/static/mini/app.js", import.meta.url), "utf8").replace(/\r\n/g, "\n");

function extract(name, next, isAsync = false) {
  const prefix = isAsync ? "async function " : "function ";
  const a = js.indexOf(prefix + name + "(");
  const b = js.indexOf("\nfunction " + next + "(", a);
  assert.ok(a >= 0 && b > a, "Cannot isolate function: " + name);
  return js.slice(a, b);
}

// Test the real switchToView function with a small, deterministic fake UI.
const classes = () => ({
  active: false,
  toggle(name, value) { if (name === "active") this.active = Boolean(value); },
  contains(name) { return name === "active" && this.active; },
});
const views = Object.fromEntries(["games", "cards", "wallet", "admin"].map((name) => [
  "view-" + name, { classList: classes(), setAttribute() {} },
]));
const nav = ["games", "cards", "wallet", "admin"].map((name) => ({
  name, classList: classes(),
  getAttribute(attr) { return attr === "data-view" ? this.name : null; },
  setAttribute() {}, removeAttribute() {},
}));
let cardsRefreshes = 0;
let cardPolling = 0;
let stopPolling = 0;
let adminRefreshes = 0;

const navigationContext = {
  state: { admin: { enabled: false } },
  getEl(id) { return views[id] || null; },
  document: { querySelectorAll() { return nav; } },
  startCardsPolling() { cardPolling++; },
  stopCardsPolling() { stopPolling++; },
  refreshCards() { cardsRefreshes++; return Promise.resolve(); },
  refreshAdminPanel() { adminRefreshes++; return Promise.resolve(); },
  setBadge() {},
  stopAdminOpsAutoRefresh() {},
  startAdminOpsAutoRefresh() {},
  updateGameStartCountdowns() {},
};
vm.runInNewContext(
  extract("switchToView", "wireNavigation") + "\nthis.navigate = switchToView;",
  navigationContext,
);

navigationContext.navigate("cards", { skipCardsRefresh: true });
assert.equal(cardsRefreshes, 0, "Direct-card navigation must not start two card fetches");
assert.equal(cardPolling, 1, "Card polling is still enabled");
assert.equal(views["view-cards"].classList.active, true);

navigationContext.navigate("cards");
assert.equal(cardsRefreshes, 1, "Normal card nav should still refresh");
navigationContext.navigate("admin");
assert.equal(adminRefreshes, 0, "No admin data may load without admin role");
assert.equal(views["view-games"].classList.active, true, "Unauthorized admin goes to games");

const routeContext = {};
vm.runInNewContext(
  extract("notificationRoute", "updateNotificationBadge") + "\nthis.parse = notificationRoute;",
  routeContext,
);
assert.equal(routeContext.parse({}).view, "", "Unknown route must not pretend to be wallet");
assert.equal(routeContext.parse({ target_view: "wallet" }).view, "wallet");
assert.equal(routeContext.parse({ route: { view: "cards", target_id: 83 } }).targetId, 83);

const visited = [];
let walletRefreshes = 0;
let explicitCardsRefreshes = 0;
let historyOpens = 0;
let receiptOpens = 0;
const notificationContext = {
  notificationRoute: routeContext.parse,
  state: { admin: { enabled: false } },
  switchToView(view, options = {}) { visited.push({ view, options }); },
  refreshCards() { explicitCardsRefreshes++; return Promise.resolve(); },
  refreshWallet() { walletRefreshes++; return Promise.resolve(); },
  openAdminRoute() { return Promise.resolve(); },
  openLiveGame() { return Promise.resolve(); },
  openHistoryModalForGame() { historyOpens++; return Promise.resolve(); },
  openReceiptModal() { receiptOpens++; return Promise.resolve(); },
  getEl() { return { scrollIntoView() {} }; },
  showToast() {},
};
vm.runInNewContext(
  extract("openNotificationRoute", "wireAdminNotify", true) +
  "\nthis.open = openNotificationRoute;",
  notificationContext,
);

await notificationContext.open({
  route: { view: "cards", section: "wins", target_id: 83, action: "open_winning_card", meta: { card_id: 476 } },
});
assert.equal(explicitCardsRefreshes, 1);
assert.equal(historyOpens, 1);
assert.equal(visited.at(-1).view, "cards");
assert.equal(visited.at(-1).options.skipCardsRefresh, true);

await notificationContext.open({
  route: { view: "wallet", section: "bank_deposits", action: "open_receipt", target_id: 7 },
  receipt_kind: "bank_deposit", receipt_id: 7,
});
assert.equal(walletRefreshes, 1);
assert.equal(receiptOpens, 1);
assert.equal(visited.at(-1).view, "wallet");

await notificationContext.open({});
assert.equal(visited.at(-1).view, "games", "Unknown notification must not land in wallet");
assert.equal(walletRefreshes, 1, "Unknown notification must not refresh financial data");
assert.ok(js.includes('switchToView("cards", { skipCardsRefresh: true });\n  await refreshCards({ silent: true });'));
assert.ok(
  /await openNotificationRoute\(item\);[\s\S]*?state\.notificationReadIds\.add\(String\(item\.id\)\)/.test(js),
  "Notifications must not be marked read before a successful route"
);
assert.ok(
  /await openReceiptModal\(route\.receiptKind, route\.receiptId\);[\s\S]*?state\.notificationReadIds\.add\(String\(item\.id\)\)/.test(js),
  "Receipts must not be marked read before their modal opens"
);
console.log("PASS: card navigation avoids duplicate loads; finance, win, and unknown notification routes are correct.");
