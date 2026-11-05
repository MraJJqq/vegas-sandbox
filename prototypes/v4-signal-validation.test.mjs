import test from "node:test";
import assert from "node:assert/strict";
import { validateV12SignalRows } from "./v4-signal-validation.mjs";

const contracts = new Set(["BTCUSDT", "AAPLUSDT"]);
const good = {
  symbol: "BTCUSDT", formal_signal: true, candle_timestamp_ms: 1793844000000,
  filter_side: "空", tunnels: ["中锋", "红峰"]
};

test("accepts a valid formal signal row", () => {
  assert.equal(validateV12SignalRows([good], contracts).length, 1);
});
test("rejects unknown contract", () => {
  assert.throws(() => validateV12SignalRows([{ ...good, symbol: "UNKNOWNUSDT" }], contracts));
});
test("rejects malformed timestamp, direction and tunnel list", () => {
  assert.throws(() => validateV12SignalRows([{ ...good, candle_timestamp_ms: "123" }], contracts));
  assert.throws(() => validateV12SignalRows([{ ...good, filter_side: "sideways" }], contracts));
  assert.throws(() => validateV12SignalRows([{ ...good, tunnels: ["RSI"] }], contracts));
});
test("rejects duplicate signal identity", () => {
  assert.throws(() => validateV12SignalRows([good, good], contracts));
});
test("allows a confirmed empty signal list", () => {
  assert.deepEqual(validateV12SignalRows([], contracts), []);
});
