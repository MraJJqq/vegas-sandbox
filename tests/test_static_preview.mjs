import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const [css, moduleSource, page] = await Promise.all([
  readFile(new URL("../bottom-signal/bottom-signal.css", import.meta.url), "utf8"),
  readFile(new URL("../bottom-signal/bottom-signal.mjs", import.meta.url), "utf8"),
  readFile(new URL("../index.html", import.meta.url), "utf8")
]);

test("signal bar is fixed to bottom-right and respects device safe areas", () => {
  assert.match(css, /position:\s*fixed/);
  assert.match(css, /right:\s*max\(/);
  assert.match(css, /bottom:\s*max\(/);
  assert.match(css, /env\(safe-area-inset-right\)/);
  assert.match(css, /env\(safe-area-inset-bottom\)/);
  assert.match(css, /justify-content:\s*flex-end/);
});

test("signal sequence wraps at the right without scrolling or duplicated lanes", () => {
  assert.match(css, /flex-wrap:\s*wrap/);
  assert.doesNotMatch(moduleSource, /requestAnimationFrame|setInterval|ticker-duration|is-moving|vegas-signal-lane|cloneNode/);
  assert.doesNotMatch(css, /@keyframes|animation:/);
});

test("sandbox page has explicit demo mode and Bark live feed", () => {
  assert.match(page, /params\.get\("demo"\) === "1"/);
  assert.match(page, /DEMO DATA/);
  assert.match(page, /Vegasbark\/main\/public\/signals\.json/);
});
