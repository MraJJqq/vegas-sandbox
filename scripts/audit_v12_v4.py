#!/usr/bin/env python3
"""Read-only static contract checks for the V12/V4 sandbox audit."""
from __future__ import annotations
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(sys.argv[1]).resolve()
V12 = ROOT / "source" / "v12-main"
V4 = ROOT / "source" / "v4"

def read(path: pathlib.Path) -> str:
    if not path.is_file():
        raise AssertionError(f"missing source file: {path}")
    return path.read_text(encoding="utf-8")

def assigned_literal(source: str, name: str):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError(f"assignment {name} not found")

config = read(V12 / "v12" / "config.py")
scanner = read(V12 / "v12" / "scanner.py")
state = read(V12 / "v12" / "state.py")
bark = read(V12 / "v12" / "bark.py")
watchdog = read(V12 / "v12" / "watchdog.py")
workflow = read(V12 / ".github" / "workflows" / "v12-bitget-scan.yml")
feed = read(V4 / "assets" / "js" / "signals" / "v12-feed-v4.js")
ticker = read(V4 / "assets" / "js" / "signals" / "ticker-v4.js")
app = read(V4 / "assets" / "js" / "app-v4.js")
universe = read(V4 / "assets" / "js" / "core" / "universe-v4.js")
architecture = read(V4 / "docs" / "architecture.md")

core = assigned_literal(config, "CORE_SYMBOLS")
stocks = assigned_literal(config, "STOCK_SYMBOLS")
v12_symbols = {"SKHYUSDT" if s == "SKHYNIX" else f"{s}USDT" for s in (*core, *stocks)}
definitions_match = re.search(r"const DEFINITIONS = (\[.*?\]);\s*\n\nexport const INSTRUMENTS", universe, re.S)
assert definitions_match, "V4 instrument definitions not found"
definitions = ast.literal_eval(definitions_match.group(1))
v4_symbols = {row[1] for row in definitions}
assert len(v12_symbols) == 27, f"V12 symbol count is {len(v12_symbols)}"
assert len(v4_symbols) == 27, f"V4 symbol count is {len(v4_symbols)}"
assert v12_symbols == v4_symbols, f"V12/V4 universe mismatch: V12-only={v12_symbols-v4_symbols}, V4-only={v4_symbols-v12_symbols}"

assert "if report.get(\"scan_status\")!=\"complete\"" in scanner
assert "report[\"symbols_ok\"]==report[\"symbols_total\"]" in scanner
assert "return 0 if report.get(\"scan_status\")==\"complete\"" in scanner
assert "x.get(\"date\")==day" in state and "candle_timestamp_ms" in state
assert "BARK_PENDING_PATH" in bark and "uncertain" in bark and "retryable" in bark
assert "RECOVERY_LOCK_TIMEOUT_MINUTES" in watchdog and "recovery_slot" in watchdog
assert "concurrency:" in workflow and "cancel-in-progress: false" in workflow
assert "V12_LAUNCH_APPROVED" in workflow and "V12_ENABLED" in workflow

assert "schema_version !== 1" in feed
assert "payload.signal_day !== beijingSignalDay(nowMs)" in feed
assert "payload.symbols_ok !== expected" in feed and "seenSymbols.size !== expected" in feed
assert "DEFAULT_CACHE_MS = 30_000" in feed
assert "lifecycle.interval(refreshSignals, 300_000)" in app
assert "feed.suspend()" in app and "feed.destroy()" in app
assert "formal_signal === true" in ticker
assert "V12 signals never alter" in architecture

warnings = []
if 'scan_id=str(report.get("started_at")' in bark and 'fingerprint=hashlib.sha256(f"{day}\\n{scan_id}\\n{body}"' in bark:
    warnings.append("BARK_SLOT_IDEMPOTENCY: fingerprint is per scan start time, not a stable scheduled slot; separate duplicate runs can send the same body.")
if "signal?.formal_signal === true" in ticker and "signal.candle_timestamp_ms" not in feed:
    warnings.append("FEED_ROW_VALIDATION: outer feed is strict, but individual signal rows are not fully schema-validated before ticker rendering.")

print("PASS: V12 and V4 both define exactly the same 27 Bitget contracts.")
print("PASS: complete-scan publication, daily merge/reset, Bark pending-state and watchdog lock guards are present.")
print("PASS: V4 validates current-day/full-universe feed, caches reads and suspends background work.")
print("PASS: V12 signal rendering remains separate from V4 market universe and rotation.")
for warning in warnings:
    print("REVIEW:", warning)
print(f"RESULT: {4} static contract groups passed; {len(warnings)} review item(s).")
