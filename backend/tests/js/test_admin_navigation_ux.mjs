import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const base = new URL("../../app/static/mini/", import.meta.url);
const js = readFileSync(new URL("app.js", base), "utf8");
const html = readFileSync(new URL("index.html", base), "utf8");
const css = readFileSync(new URL("ux-v2.css", base), "utf8");

function fn(name, nextName) {
  const from = js.indexOf("function " + name + "(");
  const until = js.indexOf("\nfunction " + nextName + "(", from);
  assert.ok(from >= 0 && until > from, "Function missing: " + name);
  return js.slice(from, until);
}

for (const id of [
  "adminOpsDashboard", "adminGamesList", "adminDrawModeShell",
  "adminAutopilotList", "adminDepositsList", "adminWithdrawsList",
]) {
  assert.match(html, new RegExp('data-admin-jump="' + id + '"'));
  assert.match(html, new RegExp('id="' + id + '"'));
}
assert.match(css, /\.admin-quick-nav-v2\s*\{/);
assert.match(css, /\.admin-game-list-item-v2\.is-selected\s*\{/);
assert.ok(js.includes("syncAdminSelectedGameListV2()"));
assert.ok(js.includes("openLiveBarGame(gid).catch("));

const details = {
  open: false,
  scrollIntoView() { this.scrolled = true; },
};
const target = { closest(query) { return query === "details" ? details : null; } };
const switches = [];
const nodes = {};
const context = {
  state: { admin: { enabled: true } },
  getEl(id) { return id === "adminDepositsList" || id === "adminAutopilotList" ? target : null; },
  setAdminGameMode(mode) { switches.push(mode); },
  showToast() { throw new Error("Missing target"); },
};
vm.runInNewContext(
  'const ADMIN_QUICK_TARGETS_V2 = {' +
  js.split("const ADMIN_QUICK_TARGETS_V2 = {")[1].split("};")[0] + "};\n" +
  fn("jumpToAdminSectionV2", "wireAdminQuickNavigationV2") +
  "\nthis.jump = jumpToAdminSectionV2;",
  context,
);
context.jump("adminDepositsList");
assert.equal(details.open, true);
assert.equal(details.scrolled, true);
context.jump("adminAutopilotList");
assert.equal(switches.at(-1), "AUTO");
context.jump("__unknown__"); // Must ignore non-whitelisted destinations.
assert.equal(switches.length, 1);

// A game shown as read-only must never expose enabled mutating controls.
const buttons = new Map();
const readOnlyContext = {
  state: {
    admin: { selectedGameId: 12, autoDrawByGame: new Map([[12, { draw_mode: "MANUAL", status: "STOPPED", locked: true }]]) },
  },
  getAdminGameById() { return { status: "RUNNING", can_manage: false }; },
  adminLiveLinkForGame() { return "https://example.invalid/live"; },
  getEl(id) {
    if (!buttons.has(id)) {
      buttons.set(id, {
        disabled: false,
        classList: { toggle() {} },
        setAttribute() {},
        removeAttribute() {},
      });
    }
    return buttons.get(id);
  },
};
vm.runInNewContext(
  fn("updateAdminActionButtons", "requireAdminGameStatus") +
  "\nthis.checkActions = updateAdminActionButtons;",
  readOnlyContext,
);
readOnlyContext.checkActions();
for (const id of ["adminCallBtn", "adminUndoBtn", "adminStartBtn", "adminSetLiveBtn", "adminSendLiveBtn"]) {
  assert.equal(buttons.get(id)?.disabled, true, "Read-only action enabled: " + id);
}
assert.equal(buttons.get("adminAutoDrawInterval")?.disabled, true);

console.log("PASS: admin section routing, safe destinations, read-only controls and selected game UI.");
