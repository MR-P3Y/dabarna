import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const base = new URL("../../app/static/mini/", import.meta.url);
const source = readFileSync(new URL("app.js", base), "utf8");
const html = readFileSync(new URL("index.html", base), "utf8");

function extractFunction(name, nextName) {
  const begin = source.indexOf("function " + name + "(");
  const end = source.indexOf("\nfunction " + nextName + "(", begin);
  assert.ok(begin >= 0 && end > begin, "Cannot isolate " + name);
  return source.slice(begin, end);
}

const context = { toFaDigits: String };
vm.runInNewContext(
  extractFunction("gameRuleUiMeta", "drawGamesOverview") +
  "\n" + extractFunction("cardProgressInfo", "renderCardsActive") +
  "\nthis.getGameRuleUiMeta = gameRuleUiMeta;" +
  "\nthis.getCardProgressInfo = cardProgressInfo;",
  context,
);

const full = context.getGameRuleUiMeta({ game_rule: "FULL_CARD", game_level: "HIGH" });
assert.equal(full.label, "پرکردنی");
assert.match(full.description, /۱۵ عدد/);
assert.match(full.description, /بدون تورنا/);

const line = context.getGameRuleUiMeta({ game_rule: "LINE", game_level: "LOW" });
assert.equal(line.levelLabel, "خطی ۱");
assert.match(line.description, /تورنا/);
assert.match(line.description, /خطی/);

const legacy = context.getGameRuleUiMeta({ game_rule: "LEGACY" });
assert.equal(legacy.rule, "LEGACY");

const lineCard = [
  0, 0, 0, 31, 45, 50, 0, 70, 80,
  2, 0, 22, 35, 0, 0, 61, 0, 86,
  6, 13, 0, 37, 0, 55, 0, 78, 0,
];
const torna = context.getCardProgressInfo(lineCard, new Set([31, 45, 50]), "LINE");
assert.equal(torna.percent, 60);
assert.match(torna.label, /۳ از ۵/);
assert.match(torna.ruleHint, /تورنا/);
const completeLine = context.getCardProgressInfo(lineCard, new Set([31, 45, 50, 70, 80]), "LINE");
assert.equal(completeLine.percent, 100);

const fullCard = [
  3, 0, 0, 38, 0, 51, 65, 0, 80,
  7, 13, 28, 0, 0, 0, 68, 0, 81,
  0, 0, 0, 39, 45, 52, 0, 74, 85,
];
const afterFive = context.getCardProgressInfo(fullCard, new Set([3, 38, 51, 65, 80]), "FULL_CARD");
assert.equal(afterFive.percent, 33);
assert.match(afterFive.ruleHint, /بدون تورنا/);

const afterAll = context.getCardProgressInfo(fullCard, new Set(fullCard.filter((n) => n > 0)), "FULL_CARD");
assert.equal(afterAll.percent, 100);

assert.ok(html.includes('id="gamesOverview"'));
assert.ok(html.includes("quick-guide-collapse"));
assert.ok(source.includes('data-action="${isLobby ? "buy" : "live"}"'));
assert.ok(!source.includes("روند شکل‌گیری جایزه"));
assert.ok(!source.includes("soldCards / maxSold"));

console.log("PASS: rules, row progress, full-card progress, and game dashboard.");
