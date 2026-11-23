const SYMBOL_RE = /^[A-Z0-9]{2,24}$/;

export function normalizeSignalFeed(payload, now = Date.now(), maxAgeMs = 30 * 60 * 1000) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new TypeError("Signal feed must be an object");
  }
  if (payload.schema_version !== 1) throw new TypeError("Unsupported signal feed schema");
  if (payload.source !== "Vegasbark") throw new TypeError("Unexpected signal source");
  if (typeof payload.generated_at !== "string") throw new TypeError("Missing generated_at");
  const generatedAt = Date.parse(payload.generated_at);
  if (!Number.isFinite(generatedAt) || generatedAt > now + 60_000) {
    throw new TypeError("Invalid signal timestamp");
  }
  if (now - generatedAt > maxAgeMs) throw new RangeError("Signal feed is stale");
  if (!Array.isArray(payload.symbols)) throw new TypeError("symbols must be an array");

  const seen = new Set();
  const symbols = [];
  for (const raw of payload.symbols) {
    if (typeof raw !== "string") throw new TypeError("Invalid symbol");
    const symbol = raw.trim().toUpperCase().replace(/USDT$/, "");
    if (!SYMBOL_RE.test(symbol)) throw new TypeError("Invalid symbol");
    if (!seen.has(symbol)) {
      seen.add(symbol);
      symbols.push(symbol);
    }
  }
  return Object.freeze({
    generatedAt: new Date(generatedAt).toISOString(),
    symbols: Object.freeze(symbols)
  });
}
