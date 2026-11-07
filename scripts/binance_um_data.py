#!/usr/bin/env python3
"""Public Binance USD-M Futures market-data client and connectivity probe."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import requests

REST_BASE = "https://fapi.binance.com"
WS_BASE = "wss://fstream.binance.com/ws"
SYMBOLS = ("XAUUSDT", "BTCUSDT", "CLUSDT", "SNDKUSDT")
INTERVALS = ("4h", "8h", "12h", "1d")
EMA_SPANS = (12, 144, 169, 576, 676)
INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000,
    "4h": 14_400_000, "6h": 21_600_000, "8h": 28_800_000,
    "12h": 43_200_000, "1d": 86_400_000, "3d": 259_200_000,
    "1w": 604_800_000, "1M": 2_592_000_000,
}


class BinanceAccessError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class BinanceUMClient:
    """Binance USD-M Futures REST + WebSocket public market-data client."""

    def __init__(self, base_url: str = REST_BASE, timeout: int = 15,
                 session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "vegas-sandbox-binance-market-data/1.0",
            "Accept": "application/json",
        })

    def _get(self, path: str, params: dict | None = None):
        url = self.base_url + path
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise BinanceAccessError(f"Network error calling {url}: {exc}") from exc
        if response.status_code == 451:
            raise BinanceAccessError(
                "Binance returned HTTP 451: this execution region is not permitted "
                "to access this market-data endpoint.", 451)
        if response.status_code in (418, 429):
            raise BinanceAccessError(
                f"Binance rate/security limit HTTP {response.status_code}: "
                f"{response.text[:300]}", response.status_code)
        if not response.ok:
            raise BinanceAccessError(
                f"Binance HTTP {response.status_code}: {response.text[:300]}",
                response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise BinanceAccessError("Binance returned invalid JSON") from exc

    def ping(self) -> bool:
        self._get("/fapi/v1/ping")
        return True

    def server_time(self) -> dict:
        data = self._get("/fapi/v1/time")
        stamp = int(data["serverTime"])
        return {"server_time_ms": stamp,
                "server_time_utc": datetime.fromtimestamp(
                    stamp / 1000, timezone.utc).isoformat()}

    def exchange_info(self) -> dict:
        return self._get("/fapi/v1/exchangeInfo")

    def symbols(self) -> dict[str, dict]:
        info = self.exchange_info()
        return {item["symbol"]: item for item in info.get("symbols", [])}

    @staticmethod
    def _parse_kline(row: list) -> dict:
        return {
            "open_time": int(row[0]),
            "open": float(row[1]), "high": float(row[2]),
            "low": float(row[3]), "close": float(row[4]),
            "volume": float(row[5]), "close_time": int(row[6]),
            "quote_volume": float(row[7]), "trade_count": int(row[8]),
            "taker_buy_volume": float(row[9]),
            "taker_buy_quote_volume": float(row[10]),
        }

    def klines(self, symbol: str, interval: str = "8h", limit: int = 800,
               start_time: int | None = None,
               end_time: int | None = None) -> list[dict]:
        if interval not in INTERVAL_MS:
            raise ValueError(f"Unsupported Binance interval: {interval}")
        if not 1 <= limit <= 1500:
            raise ValueError("Binance kline limit must be between 1 and 1500")
        params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        rows = self._get("/fapi/v1/klines", params)
        return [self._parse_kline(row) for row in rows]

    def klines_range(self, symbol: str, interval: str, start_time: int,
                     end_time: int, limit: int = 1000) -> list[dict]:
        """Fetch a complete time range using Binance's paginated REST endpoint."""
        if interval not in INTERVAL_MS:
            raise ValueError(f"Unsupported Binance interval: {interval}")
        if not 1 <= limit <= 1500:
            raise ValueError("Binance kline limit must be between 1 and 1500")
        step = INTERVAL_MS[interval]
        cursor, end_time = int(start_time), int(end_time)
        out: dict[int, dict] = {}
        while cursor < end_time:
            batch = self.klines(symbol, interval, limit, cursor, end_time)
            if not batch:
                break
            for candle in batch:
                if start_time <= candle["open_time"] < end_time:
                    out[candle["open_time"]] = candle
            next_cursor = batch[-1]["open_time"] + step
            if next_cursor <= cursor:
                raise BinanceAccessError("Kline pagination did not advance")
            cursor = next_cursor
            if len(batch) < limit:
                break
            time.sleep(0.05)
        return [out[key] for key in sorted(out)]

    def websocket_connect(self, symbol: str = "BTCUSDT",
                          interval: str = "8h", timeout: int = 8) -> dict:
        """Verify the official USD-M kline stream handshake, then close cleanly."""
        try:
            import websocket
        except ImportError:
            return {"connected": False, "error": "websocket-client is not installed"}
        url = f"{WS_BASE}/{symbol.lower()}@kline_{interval}"
        try:
            ws = websocket.create_connection(url, timeout=timeout,
                                             enable_multithread=True)
            status = getattr(ws, "status", None)
            ws.close()
            return {"connected": True, "url": url, "handshake_status": status}
        except Exception as exc:
            return {"connected": False, "url": url, "error": str(exc)[:500]}

    def stream_kline(self, symbol: str, interval: str,
                     on_message: Callable[[dict], None],
                     on_error: Callable[[Exception], None] | None = None):
        """Run a live kline stream; caller controls lifecycle by closing app."""
        try:
            import websocket
        except ImportError as exc:
            raise BinanceAccessError("Install websocket-client to stream") from exc
        url = f"{WS_BASE}/{symbol.lower()}@kline_{interval}"

        def handle(_ws, message: str):
            on_message(json.loads(message))

        def handle_error(_ws, error):
            if on_error:
                on_error(error if isinstance(error, Exception) else RuntimeError(str(error)))

        app = websocket.WebSocketApp(url, on_message=handle, on_error=handle_error)
        app.run_forever(ping_interval=150, ping_timeout=10)
        return app


def ema(values: Iterable[float], span: int) -> list[float | None]:
    data = list(values)
    result: list[float | None] = [None] * len(data)
    if span < 1:
        raise ValueError("EMA span must be positive")
    if len(data) < span:
        return result
    value = sum(data[:span]) / span
    result[span - 1] = value
    alpha = 2 / (span + 1)
    for index in range(span, len(data)):
        value = alpha * data[index] + (1 - alpha) * value
        result[index] = value
    return result


def build_report(client: BinanceUMClient, history_bars: int = 800,
                 symbols: tuple[str, ...] = SYMBOLS) -> dict:
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "market": "Binance USD-M perpetual futures",
        "rest_base": REST_BASE, "websocket_base": WS_BASE,
        "history_bars_requested": history_bars,
        "intervals": list(INTERVALS), "ema_spans": list(EMA_SPANS),
        "rest": {"status": "pending"}, "websocket": {"status": "pending"},
        "symbols": {}, "errors": [],
    }
    rest_error = None
    try:
        client.ping()
        report["rest"] = {"status": "connected", **client.server_time()}
        symbol_map = client.symbols()
    except Exception as exc:
        rest_error = str(exc)
        report["rest"] = {"status": "failed", "error": rest_error}
        report["errors"].append({"stage": "rest_connectivity", "error": rest_error})
        symbol_map = {}

    for symbol in symbols:
        meta = symbol_map.get(symbol)
        item = {
            "listed": meta is not None,
            "status": meta.get("status") if meta else None,
            "contract_type": meta.get("contractType") if meta else None,
            "quote_asset": meta.get("quoteAsset") if meta else None,
            "timeframes": {},
        }
        report["symbols"][symbol] = item
        if rest_error:
            item["status_note"] = "Not checked because the REST endpoint was inaccessible."
            continue
        if not meta:
            item["status_note"] = "Not listed in Binance USD-M exchangeInfo; no substitute used."
            continue
        for interval in INTERVALS:
            try:
                candles = client.klines(symbol, interval, history_bars)
                closes = [c["close"] for c in candles]
                indicators = {}
                for span in EMA_SPANS:
                    values = ema(closes, span)
                    last = values[-1] if values else None
                    indicators[str(span)] = {"available": last is not None,
                                             "last_value": last}
                item["timeframes"][interval] = {
                    "bars": len(candles),
                    "first_open_time": candles[0]["open_time"] if candles else None,
                    "last_open_time": candles[-1]["open_time"] if candles else None,
                    "last_close": candles[-1]["close"] if candles else None,
                    "last_candle_closed": (
                        candles[-1]["close_time"] < int(time.time() * 1000)
                        if candles else False),
                    "ema": indicators, "status": "ok" if candles else "empty",
                }
            except Exception as exc:
                item["timeframes"][interval] = {"status": "error", "error": str(exc)}
                report["errors"].append({
                    "symbol": symbol, "interval": interval, "error": str(exc)[:500]})
    report["websocket"] = client.websocket_connect("BTCUSDT", "8h")
    report["websocket"]["status"] = (
        "connected" if report["websocket"].get("connected") else "unavailable")
    btc8h = report["symbols"].get("BTCUSDT", {}).get("timeframes", {}).get("8h", {})
    report["overall_status"] = (
        "connected" if report["rest"]["status"] == "connected"
        and btc8h.get("status") == "ok"
        and report["websocket"]["status"] == "connected" else "incomplete")
    return report


def write_report(report: dict, output_dir: str):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "binance-connectivity.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Binance USD-M market-data connection check", "",
        f"- Generated: {report['generated_at_utc']}",
        f"- Overall: **{report.get('overall_status', 'failed')}**",
        f"- REST: **{report.get('rest', {}).get('status', 'failed')}**",
        f"- WebSocket: **{report.get('websocket', {}).get('status', 'unknown')}**",
        f"- REST endpoint: {REST_BASE}", f"- WebSocket endpoint: {WS_BASE}", "",
        "| Symbol | Listed | Status | 4H bars | 8H bars | 12H bars | 1D bars |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for symbol, item in report.get("symbols", {}).items():
        tf = item.get("timeframes", {})
        counts = [tf.get(x, {}).get("bars", 0) for x in INTERVALS]
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            symbol, item.get("listed"), item.get("status") or "not listed", *counts))
    lines += ["", "## Notes",
        "- Public Binance USD-M Futures data; no API key is required.",
        "- Native REST klines are used, including native 8h candles; no resampling.",
        "- The WebSocket check verifies the official live kline-stream handshake.",
        "- EMA uses an SMA seed over the first N closes, then standard EMA recurrence.",
        "- HTTP 451 is reported as a regional restriction and is not bypassed."]
    if report.get("errors"):
        lines += ["", "## Errors"] + [f"- {e}" for e in report["errors"]]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print((out / "report.md").read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-bars", type=int, default=800)
    parser.add_argument("--output-dir", default="results/binance-market-data")
    args = parser.parse_args()
    if not 1 <= args.history_bars <= 1500:
        parser.error("--history-bars must be between 1 and 1500")
    try:
        report = build_report(BinanceUMClient(), args.history_bars)
    except Exception as exc:
        report = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "overall_status": "failed",
            "rest": {"status": "failed", "error": str(exc)},
            "websocket": {"status": "not_checked"},
            "symbols": {}, "errors": [{"stage": "connection", "error": str(exc)}],
        }
        write_report(report, args.output_dir)
        return 1
    write_report(report, args.output_dir)
    return 0 if report["overall_status"] == "connected" else 1


if __name__ == "__main__":
    sys.exit(main())
