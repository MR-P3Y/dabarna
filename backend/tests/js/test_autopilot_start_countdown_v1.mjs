import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const base = new URL("../../app/static/mini/", import.meta.url);
const source = readFileSync(new URL("app.js", base), "utf8");
const html = readFileSync(new URL("index.html", base), "utf8");
const css = readFileSync(new URL("ux-v2.css", base), "utf8");

const begin = source.indexOf("let gameStartCountdownTicker = null;");
const end = source.indexOf("\nfunction drawGames(items) {", begin);
assert.ok(begin > 0 && end > begin, "Autopilot countdown helpers must exist");

const ctx = {
  Date,
  parseApiDate: (value) => new Date(value),
  toFaDigits: (value) => String(value),
  safeText: (value) => String(value),
  state: { gamesCache: [], soundEnabled: false },
  getEl: () => null,
  setInterval: () => 1,
};
vm.runInNewContext(
  source.slice(begin, end) +
  "\nthis.getClock = autopilotGameStartClock;" +
  "\nthis.getHtml = autopilotGameStartClockHtml; this.tick = tickAutopilotGameStartClocks;",
  ctx,
);
const clock = ctx.getClock;
const render = ctx.getHtml;
const now = Date.parse("2026-11-10T15:00:00.000Z");
const game = {
  id: 91,
  status: "LOBBY",
  execution_source: "SYSTEM",
  countdown_enabled: true,
  countdown_seconds: 30,
  draw_mode: "AUTO",
  scheduled_start_at: "2026-11-10T15:00:30Z",
};

assert.equal(clock(game, now).seconds, 30);
assert.equal(clock(game, now).progress, 100);
assert.equal(clock(game, now + 27_000).seconds, 3);
assert.equal(clock(game, now + 27_000).urgent, true);
assert.equal(clock(game, now + 29_000).seconds, 1);
assert.equal(clock(game, now + 30_001).seconds, 0);
assert.equal(clock(game, now + 30_001).pending, true, "zero is NOT the start command");
assert.equal(clock({ ...game, status: "RUNNING" }, now), null);
assert.equal(clock({ ...game, execution_source: "ADMIN" }, now), null);
assert.equal(clock({ ...game, countdown_enabled: false }, now), null);
for (const deadline of [null, "", "invalid"]) {
  assert.equal(clock({ ...game, scheduled_start_at: deadline }, now), null);
}
assert.equal(clock({ ...game, countdown_seconds: 60 }, now).total, 60, "Autopilot settings are authoritative");

const markup = render(game, clock(game, now + 27_000));
assert.match(markup, /data-autopilot-clock="91"/);
assert.match(markup, /autopilot-start-clock-ring/);
assert.match(markup, /شماره‌خوان خودکار/);
assert.match(markup, /is-urgent/);

assert.ok(source.includes('server_time_utc'), "server clock offset is required");
assert.ok(source.includes('tickAutopilotGameStartClocks();'));
assert.ok(source.includes('startAutopilotGameStartClockTicker();'));
assert.ok(source.includes('gameStartCountdownFeedback.get(key) !== view.seconds'));
assert.ok(!source.slice(begin, end).includes('apiFetch('), "countdown must not trigger backend writes");
assert.ok(css.includes("Autopilot game-start countdown v1"));
assert.ok(css.includes("prefers-reduced-motion"));
assert.ok(html.includes("ux-v2.css?v=remaining-ux-v1"));
assert.ok(html.includes("app.js?v=remaining-ux-v1"));

// Exercise the real ticker with two simultaneously urgent games.
const noOp = () => {};
const clockCard = id => ({getAttribute: () => id, style: {setProperty: noOp},
  querySelector: () => null, classList: {toggle: noOp}, closest: () => null});
ctx.Date = class extends Date { static now() { return now + 27_000; } };
ctx.getEl = id => id === "gamesList"
  ? { querySelectorAll: () => [clockCard(91), clockCard(92)] }
  : { classList: {contains: () => true} };
ctx.document = {visibilityState: "visible", querySelectorAll: () => []};
ctx.state.gamesCache = [game, {...game, id: 92}];
let beeps = 0, vibrations = 0;
ctx.tg = { HapticFeedback: { impactOccurred: () => { vibrations++; } } };
ctx.playTone = () => { beeps++; };
ctx.tick();
assert.equal(beeps, 0);
assert.equal(vibrations, 0);
ctx.Date.now = () => now + 28_000;
ctx.state.soundEnabled = true;
ctx.tick();
assert.equal(beeps, 1);
assert.equal(vibrations, 0);
ctx.Date.now = () => now + 29_000;
ctx.state.soundEnabled = false;
ctx.state.countdownVibration = true;
ctx.tick();
ctx.tick();
assert.equal(beeps, 1);
assert.equal(vibrations, 1);
console.log("PASS: Autopilot-authoritative countdown, UI, sound/haptic safeguards and pending state.");
