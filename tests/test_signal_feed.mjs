import test from "node:test";
import assert from "node:assert/strict";
import { normalizeSignalFeed } from "../bottom-signal/signal-feed.mjs";

const now = Date.parse("2026-11-23T08:00:00+08:00");
const feed = (overrides = {}) => ({
  schema_version: 1,
  source: "Vegasbark",
  generated_at: new Date(now).toISOString(),
  symbols: ["BTCUSDT", "ETHUSDT"],
  ...overrides
});

test("normalizes Bark symbols for display and preserves order", () => {
  const result = normalizeSignalFeed(feed(), now);
  assert.deepEqual(result.symbols, ["BTC", "ETH"]);
});

test("removes duplicates without reordering", () => {
  const result = normalizeSignalFeed(feed({ symbols: ["BTC", "BTCUSDT", "ETH"] }), now);
  assert.deepEqual(result.symbols, ["BTC", "ETH"]);
});

test("valid empty feed represents a real no-signal scan", () => {
  const result = normalizeSignalFeed(feed({ symbols: [] }), now);
  assert.deepEqual(result.symbols, []);
});

test("rejects unknown schema and source", () => {
  assert.throws(() => normalizeSignalFeed(feed({ schema_version: 2 }), now));
  assert.throws(() => normalizeSignalFeed(feed({ source: "other" }), now));
});

test("rejects malformed symbols", () => {
  assert.throws(() => normalizeSignalFeed(feed({ symbols: ["BTC/USDT"] }), now));
  assert.throws(() => normalizeSignalFeed(feed({ symbols: [null] }), now));
});

test("rejects stale and future feeds", () => {
  assert.throws(() => normalizeSignalFeed(feed({ generated_at: new Date(now - 31 * 60_000).toISOString() }), now), RangeError);
  assert.throws(() => normalizeSignalFeed(feed({ generated_at: new Date(now + 2 * 60_000).toISOString() }), now));
});
