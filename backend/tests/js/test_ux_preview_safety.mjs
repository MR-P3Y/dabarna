import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Script } from "node:vm";

const base = new URL("../../app/static/mini/", import.meta.url);
const html = readFileSync(new URL("../../../dev/ux-preview/index.html", import.meta.url), "utf8");

assert.match(html, /<meta name="robots" content="noindex, nofollow">/);
assert.match(html, /تمام داده‌ها ساختگی‌اند/);
assert.match(html, /href="\.\/styles\.css\?/);
assert.match(html, /href="\.\/ux-v2\.css\?/);
assert.doesNotMatch(html, /<script[^>]*src=/);
assert.doesNotMatch(html, /app\.js\?/);
assert.match(html, /id="preview-line-card"/);
assert.match(html, /id="preview-full-card"/);
assert.match(html, /data-demo-view="cards"/);

const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
assert.ok(script, "Preview script is missing");
new Script(script); // syntax-only, no DOM or network access
assert.doesNotMatch(script, /\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon)\s*\(/);
assert.doesNotMatch(script, /https?:\/\/|mini-api\/|document\.cookie|localStorage/);

const line = script.match(/const lineCard = (\[[\d,\s]+\]);/);
const full = script.match(/const fullCard = (\[[\d,\s]+\]);/);
assert.ok(line && full, "Preview ticket fixtures are missing");
for (const array of [JSON.parse(line[1]), JSON.parse(full[1])]) {
  assert.equal(array.length, 27);
  assert.equal(array.filter((n) => n > 0).length, 15);
}

console.log("PASS: safe, disconnected mock preview with valid scripts and 3x9 cards.");
