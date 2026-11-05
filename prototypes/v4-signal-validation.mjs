export function validateV12SignalRows(signals, validContracts) {
  if (!Array.isArray(signals)) throw new Error("V12 signals must be an array");
  const allowed = validContracts instanceof Set ? validContracts : new Set(validContracts);
  const seen = new Set();
  for (const signal of signals) {
    if (!signal || typeof signal !== "object" || Array.isArray(signal)) {
      throw new Error("V12 signal row must be an object");
    }
    const symbol = String(signal.symbol || "").trim().toUpperCase();
    if (signal.formal_signal !== true || !allowed.has(symbol)) {
      throw new Error("V12 signal row has an invalid formal signal or contract");
    }
    if (!Number.isSafeInteger(signal.candle_timestamp_ms) || signal.candle_timestamp_ms <= 0) {
      throw new Error("V12 signal timestamp is invalid");
    }
    if (!["多", "空"].includes(signal.filter_side)) {
      throw new Error("V12 signal direction is invalid");
    }
    if (!Array.isArray(signal.tunnels) || !signal.tunnels.length ||
        signal.tunnels.some(x => !["中锋", "红峰"].includes(x)) ||
        new Set(signal.tunnels).size !== signal.tunnels.length) {
      throw new Error("V12 signal tunnel list is invalid");
    }
    const key = [symbol, signal.candle_timestamp_ms, signal.filter_side].join("|");
    if (seen.has(key)) throw new Error("V12 signal row is duplicated");
    seen.add(key);
  }
  return signals;
}
