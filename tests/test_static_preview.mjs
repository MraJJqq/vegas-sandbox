import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const [css, moduleSource, page] = await Promise.all([
  readFile(new URL("../bottom-signal/bottom-signal.css", import.meta.url), "utf8"),
  readFile(new URL("../bottom-signal/bottom-signal.mjs", import.meta.url), "utf8"),
  readFile(new URL("../index.html", import.meta.url), "utf8")
]);

test("signal bar is fixed to bottom center", () => {
  assert.match(css, /position:\s*fixed/);
  assert.match(css, /left:\s*50%/);
  assert.match(css, /bottom:/);
  assert.match(css, /translateX\(-50%\)/);
});

test("signal module contains no scrolling or duplicated ticker lane", () => {
  assert.doesNotMatch(moduleSource, /requestAnimationFrame|setInterval|ticker-duration|is-moving|vegas-signal-lane|cloneNode/);
  assert.doesNotMatch(css, /@keyframes|animation:/);
});

test("sandbox page has explicit demo mode and Bark live feed", () => {
  assert.match(page, /params\.get\("demo"\) === "1"/);
  assert.match(page, /DEMO DATA/);
  assert.match(page, /Vegasbark\/main\/public\/signals\.json/);
});
