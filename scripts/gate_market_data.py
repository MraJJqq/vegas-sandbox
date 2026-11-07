#!/usr/bin/env python3
"""Read-only Gate.io USDT perpetual REST + WebSocket market-data probe."""
from __future__ import annotations
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import websocket

REST = "https://api.gateio.ws/api/v4"
WS = "wss://fx-ws.gateio.ws/v4/ws/usdt"
CONTRACT = "BTC_USDT"
INTERVALS = ("4h", "8h")

def rest_probe():
    out = {"base": REST, "contracts_status": None, "contract_found": False,
           "candles": {}, "errors": []}
    try:
        r = requests.get(f"{REST}/futures/usdt/contracts", timeout=15)
        out["contracts_status"] = r.status_code
        r.raise_for_status()
        contracts = r.json()
        out["contract_found"] = any(x.get("name") == CONTRACT for x in contracts)
        for interval in INTERVALS:
            try:
                resp = requests.get(
                    f"{REST}/futures/usdt/candlesticks",
                    params={"contract": CONTRACT, "interval": interval, "limit": 3},
                    timeout=15,
                )
                resp.raise_for_status()
                rows = resp.json()
                if not isinstance(rows, list) or not rows:
                    raise RuntimeError(f"empty/non-list candle response: {rows!r}")
                out["candles"][interval] = {
                    "status": "ok", "count": len(rows),
                    "latest": rows[-1],
                    "native_interval_requested": interval,
                }
            except Exception as exc:
                out["candles"][interval] = {"status": "failed", "error": str(exc)}
                out["errors"].append(f"REST {interval}: {exc}")
    except Exception as exc:
        out["errors"].append(f"REST contracts: {exc}")
    out["status"] = (
        "connected" if out["contract_found"] and
        all(out["candles"].get(x, {}).get("status") == "ok" for x in INTERVALS)
        else "failed"
    )
    return out

def websocket_probe(wait_seconds=35):
    result = {"url": WS, "subscribed": [], "events": [], "status": "failed"}
    ws = None
    try:
        ws = websocket.create_connection(WS, timeout=10, enable_multithread=True)
        ws.settimeout(2)
        for interval in ("1m", "4h", "8h"):
            req = {
                "time": int(time.time()),
                "channel": "futures.candlesticks",
                "event": "subscribe",
                "payload": [interval, CONTRACT],
            }
            ws.send(json.dumps(req))
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if not raw:
                continue
            msg = json.loads(raw)
            if msg.get("channel") == "futures.candlesticks":
                if msg.get("event") == "subscribe":
                    result["subscribed"].append({
                        "payload": msg.get("payload"),
                        "result": msg.get("result"),
                        "error": msg.get("error"),
                    })
                elif msg.get("event") == "update":
                    payload = msg.get("result")
                    if isinstance(payload, list):
                        for candle in payload:
                            result["events"].append(candle)
            if result["events"]:
                break
        result["status"] = "live_update_received" if result["events"] else "connected_no_update"
    except Exception as exc:
        result["error"] = str(exc)[:500]
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass
    return result

def main():
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "runner": {
            "github_actions": os.getenv("GITHUB_ACTIONS"),
            "runner_os": os.getenv("RUNNER_OS"),
            "runner_arch": os.getenv("RUNNER_ARCH"),
        },
        "market": "Gate.io USDT perpetual futures",
        "contract": CONTRACT,
        "rest": rest_probe(),
        "websocket": websocket_probe(),
    }
    report["overall_status"] = (
        "connected" if report["rest"]["status"] == "connected"
        and report["websocket"]["status"] == "live_update_received"
        else "incomplete"
    )
    Path("results/gate-market-data").mkdir(parents=True, exist_ok=True)
    Path("results/gate-market-data/report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Gate.io market-data probe", "",
        f"- Time (UTC): {report['generated_at_utc']}",
        f"- Runner OS: {report['runner']['runner_os']}",
        f"- Overall: **{report['overall_status']}**",
        f"- REST: **{report['rest']['status']}**",
        f"- WebSocket: **{report['websocket']['status']}**",
        f"- Contract: {CONTRACT}", "",
        "| Native timeframe | REST result | Bars returned |",
        "|---|---|---:|",
    ]
    for interval in INTERVALS:
        item = report["rest"]["candles"].get(interval, {})
        lines.append(f"| {interval} | {item.get('status', 'not tested')} | {item.get('count', 0)} |")
    lines += ["", f"- WebSocket candle updates received: {len(report['websocket'].get('events', []))}"]
    if report["rest"]["errors"]:
        lines += ["", "## REST errors"] + [f"- {e}" for e in report["rest"]["errors"]]
    if report["websocket"].get("error"):
        lines += ["", "## WebSocket error", f"- {report['websocket']['error']}"]
    Path("results/gate-market-data/report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if report["overall_status"] == "connected" else 1

if __name__ == "__main__":
    sys.exit(main())
