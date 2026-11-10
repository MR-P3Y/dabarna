import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const mini = join(dirname(fileURLToPath(import.meta.url)), "../../app/static/mini");
const html = readFileSync(join(mini, "index.html"), "utf8");
const js = readFileSync(join(mini, "app.js"), "utf8");
const css = readFileSync(join(mini, "ux-v2.css"), "utf8");
const ids = ["superCryptoToggleBtn", "superCryptoHealthBtn", "superCryptoReconcileBtn",
  "superCryptoAddressesRefreshBtn", "superBankDepositToggleBtn", "superBankCardsRefreshBtn",
  "superBankCardsNewBtn", "superBankCardSaveBtn", "superBankCardDeleteBtn",
  "superAdminGrantBtn", "superAdminRevokeBtn", "superAdminListRefreshBtn",
  "superAdminFilterInput", "superCryptoWalletSection", "superBankCardsSection"];
for (const id of ids) {
  assert.equal(html.split('id="' + id + '"').length - 1, 1, "preserve exactly one original control: " + id);
}
const categories = ["Overview", "Payments", "Accounts", "Roles", "Security"];
for (const category of categories) {
  assert.match(html, new RegExp('id="superTab' + category + '"'));
  assert.match(html, new RegExp('id="superPanel' + category + '"'));
}
assert.match(html, /id="superPanelSecurity"[\s\S]*data-admin-jump="adminAuditLogsList"/);
assert.match(html, /id="superPanelSecurity"[\s\S]*data-admin-jump="adminRiskAlertsList"/);
assert.match(css, /superadmin-panel-v13\[hidden\]/);
assert.match(js, /function showSuperAdminPanelV13\(/);
const begin = js.indexOf("function showSuperAdminPanelV13(");
const end = js.indexOf("function wireAdminQuickNavigationV2()", begin);
assert.ok(begin >= 0 && end > begin, "navigation helper located");
const tabs = categories.map(category => ({
  key: "superPanel" + category, attrs: {}, tabIndex: -1, focused: false,
  getAttribute(name) { return name === "data-super-panel-tab" ? this.key : null; },
  setAttribute(name, value) { this.attrs[name] = value; },
  focus() { this.focused = true; }
}));
const panels = categories.map(category => ({ id: "superPanel" + category, hidden: category !== "Overview" }));
const root = { open: false, querySelectorAll(sel) { return sel === "[data-super-panel-tab]" ? tabs : panels; } };
const context = { state: { admin: { canManageSuperSettings: true } }, getEl: id => id === "superAdminSection" ? root : null };
vm.runInNewContext(js.slice(begin, end), context);
assert.equal(vm.runInNewContext('showSuperAdminPanelV13("superPanelPayments")', context), true);
assert.equal(root.open, true);
assert.equal(panels.filter(p => !p.hidden).length, 1);
assert.equal(panels[1].hidden, false);
assert.equal(tabs[1].attrs["aria-selected"], "true");
assert.equal(tabs[0].attrs["aria-selected"], "false");
context.state.admin.canManageSuperSettings = false;
assert.equal(vm.runInNewContext('showSuperAdminPanelV13("superPanelRoles")', context), false);
assert.equal(panels[1].hidden, false, "unauthorized navigation does not change selection");
console.log("PASS: categorized superadmin v1.3 navigation, RBAC and control IDs");
