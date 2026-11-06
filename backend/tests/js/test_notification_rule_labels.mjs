import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const src = readFileSync(new URL("../../app/static/mini/app.js", import.meta.url), "utf8");
const html = readFileSync(new URL("../../app/static/mini/index.html", import.meta.url), "utf8");

function between(startName, nextName) {
  const from = src.indexOf("function " + startName + "(");
  const to = src.indexOf("\nfunction " + nextName + "(", from);
  assert.ok(from >= 0 && to > from, "Missing JS function " + startName);
  return src.slice(from, to);
}

const context = { EVENT_KIND_LABELS: { NUMBER_CALLED: "اعلام عدد" } };
vm.runInNewContext(
  between("winnerKindLabelByReason", "winnerKindLabelByFlags") + "\n" +
  between("eventKindLabel", "adminCreateTopicTitle") + "\n" +
  "this.prizeLabel = eventKindLabel;",
  context,
);
assert.match(context.prizeLabel("PRIZE_ROW", {}, "FULL_CARD"), /پرکردنی/);
assert.match(context.prizeLabel("PRIZE_ROW", {}, "LINE"), /خطی/);
assert.match(context.prizeLabel("PRIZE_COL", {}, "LINE"), /تورنا/);
assert.match(context.prizeLabel("PRIZE_ROW", {}, "LEGACY"), /سطری/);
assert.match(context.prizeLabel("PRIZE_ROW", { game_rule: "LINE" }, "FULL_CARD"), /خطی/);
assert.equal(context.prizeLabel("NUMBER_CALLED"), "اعلام عدد");

assert.match(src, /gameRule: st\.game_rule \|\| game\.game_rule \|\| "LEGACY"/);
assert.match(src, /eventKindLabel\(e\.kind, e\.payload \|\| \{\}, gameRule\)/);
assert.match(html, /id="notificationList"/);
console.log("PASS: mini-game live notification labels use correct rule, including old payloads.");
