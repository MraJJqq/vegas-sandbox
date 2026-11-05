from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

API = "https://api.bitget.com/api/v2/mix/market/history-candles"
SYMBOL = "BTCUSDT"
PRODUCT_TYPE = "USDT-FUTURES"
INTERVALS = {"1H": 60 * 60 * 1000, "4H": 4 * 60 * 60 * 1000}
SPANS = {"1H": [12], "4H": [144, 169, 576, 676]}
PAGE_LIMIT = 200
MAX_WINDOW_MS = 89 * 24 * 60 * 60 * 1000


def ema_v12_old(close: pd.Series, span: int) -> pd.Series:
    """V12 pre-PR-8: pandas EWM, first close is recursive seed."""
    return close.ewm(span=span, adjust=False, min_periods=span).mean()


def ema_sma_seed(close: pd.Series, span: int) -> pd.Series:
    """V12 PR-8 and V4: SMA of first span closes, then standard EMA recurrence."""
    values = close.to_numpy(dtype=np.float64, copy=False)
    out = np.full(len(values), np.nan, dtype=np.float64)
    if span < 1:
        raise ValueError("span must be positive")
    if len(values) < span:
        return pd.Series(out, index=close.index, name=close.name)
    value = sum(values[:span]) / span
    out[span - 1] = value
    alpha = 2.0 / (span + 1.0)
    for i in range(span, len(values)):
        value = values[i] * alpha + value * (1.0 - alpha)
        out[i] = value
    return pd.Series(out, index=close.index, name=close.name)


def utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def request_page(start_ms: int, end_ms: int, granularity: str) -> list:
    params = {
        "symbol": SYMBOL,
        "productType": PRODUCT_TYPE,
        "granularity": granularity,
        "startTime": str(start_ms),
        "endTime": str(end_ms),
        "limit": str(PAGE_LIMIT),
    }
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "vegas-sandbox-ema-audit/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != "00000":
        raise RuntimeError(f"Bitget API error for {granularity}: {payload}")
    return payload.get("data") or []


def fetch_candles(granularity: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    interval = INTERVALS[granularity]
    collected: dict[int, list] = {}
    chunk_start = start_ms

    while chunk_start < end_ms:
        chunk_end = min(end_ms, chunk_start + MAX_WINDOW_MS)
        page_end = chunk_end
        while page_end > chunk_start:
            rows = request_page(chunk_start, page_end, granularity)
            if not rows:
                break
            parsed = sorted(rows, key=lambda row: int(row[0]))
            for row in parsed:
                ts = int(row[0])
                if start_ms <= ts < end_ms and ts + interval <= end_ms:
                    collected[ts] = row
            oldest = min(int(row[0]) for row in parsed)
            if len(parsed) < PAGE_LIMIT or oldest <= chunk_start:
                break
            next_end = oldest - 1
            if next_end >= page_end:
                raise RuntimeError(f"Pagination stalled for {granularity} at {utc_iso(oldest)}")
            page_end = next_end
            time.sleep(0.06)
        chunk_start = chunk_end
        time.sleep(0.06)

    rows = [collected[k] for k in sorted(collected)]
    frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "base_volume", "quote_volume"])
    if frame.empty:
        return frame
    frame["timestamp"] = frame["timestamp"].astype("int64")
    for col in ("open", "high", "low", "close", "base_volume", "quote_volume"):
        frame[col] = pd.to_numeric(frame[col], errors="raise")
    return frame.reset_index(drop=True)


def compare(a: pd.Series, b: pd.Series) -> dict:
    valid = a.notna() & b.notna()
    if not valid.any():
        return {"count": 0, "max_abs": None, "max_rel_pct": None, "last_abs": None}
    av = a[valid].to_numpy(dtype=float)
    bv = b[valid].to_numpy(dtype=float)
    diff = np.abs(av - bv)
    denom = np.maximum(np.abs(bv), 1e-15)
    return {
        "count": int(valid.sum()),
        "max_abs": float(diff.max()),
        "max_rel_pct": float((diff / denom).max() * 100.0),
        "last_abs": float(diff[-1]),
    }


def save_csv(path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(path, index=False, float_format="%.12f")


def render_markdown(report: dict) -> str:
    lines = [
        "# BTCUSDT EMA Audit Result",
        "",
        f"- Generated: {report['generated_at_utc']}",
        f"- Evaluation: {report['evaluation_start_utc']} → {report['evaluation_end_utc']}",
        f"- Warm-up requested from: {report['warmup_start_utc']}",
        "- Source: Bitget USDT-FUTURES history-candles",
        "",
        "## Data coverage",
        "",
        "| Interval | Total bars | Evaluation bars | First candle (UTC) | Last closed candle (UTC) | Gaps in evaluation |",
        "|---|---:|---:|---|---|---:|",
    ]
    for c in report["interval_coverage"]:
        lines.append(f"| {c['interval']} | {c['bars_total']} | {c['bars_in_eval']} | {c['first_candle_utc']} | {c['last_closed_candle_utc']} | {c['gaps_in_eval']} |")
    lines += [
        "",
        "## EMA comparison",
        "",
        "| Interval | EMA | Valid eval bars | Old vs new max abs | Old vs new max rel % | Warmed vs 6M-only seed max abs | Latest V12 new / V4 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in report["ema_results"]:
        old = r["v12_old_vs_v12_new"]
        origin = r["full_warmup_vs_eval_only_seed"]
        latest = r["latest_v12_new_v4"]
        lines.append(
            f"| {r['interval']} | {r['ema_span']} | {r['valid_ema_bars']} | "
            f"{old['max_abs'] if old['max_abs'] is not None else 'N/A'} | "
            f"{old['max_rel_pct'] if old['max_rel_pct'] is not None else 'N/A'} | "
            f"{origin['max_abs'] if origin['max_abs'] is not None else 'N/A'} | "
            f"{latest if latest is not None else 'N/A'} |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "- V12 old: pandas EWM with adjust=False; recurrence starts from the first close, output hidden until span bars.",
        "- V12 new: SMA of first span closes, followed by the standard recursive EMA update.",
        "- V4 reference: same SMA seed and recurrence as V4 assets/js/indicators/ema-v4.js calculateEMA().",
        "- Origin sensitivity compares full pre-window warm-up with a fresh EMA seeded only from the six-month evaluation window.",
        "- V12-new/V4 is formula parity on identical source closes, not a direct readout from Bitget chart UI.",
        "- Check gap counts before interpreting any row. Nonzero gaps require a data-quality caveat.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-days", type=int, default=183)
    parser.add_argument("--warmup-days", type=int, default=365)
    parser.add_argument("--out", default="results")
    args = parser.parse_args()

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    eval_start_ms = now_ms - args.start_days * 24 * 60 * 60 * 1000
    fetch_start_ms = eval_start_ms - args.warmup_days * 24 * 60 * 60 * 1000
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries = []
    comparison_rows = []
    coverage = []

    for granularity, interval in INTERVALS.items():
        print(f"Downloading {SYMBOL} {granularity} Bitget futures candles...", flush=True)
        candles = fetch_candles(granularity, fetch_start_ms, now_ms)
        if candles.empty:
            raise RuntimeError(f"No Bitget candles returned for {granularity}")
        candles["time_utc"] = pd.to_datetime(candles["timestamp"], unit="ms", utc=True)
        candles = candles.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
        eval_mask = (candles["timestamp"] >= eval_start_ms) & (candles["timestamp"] + interval <= now_ms)
        eval_candles = candles.loc[eval_mask].copy()
        gaps = int((candles["timestamp"].diff().dropna() != interval).sum())
        eval_gaps = int((eval_candles["timestamp"].diff().dropna() != interval).sum())
        coverage.append({
            "interval": granularity,
            "bars_total": int(len(candles)),
            "bars_in_eval": int(len(eval_candles)),
            "first_candle_utc": utc_iso(int(candles["timestamp"].iloc[0])),
            "last_closed_candle_utc": utc_iso(int(candles["timestamp"].iloc[-1])),
            "gaps_total": gaps,
            "gaps_in_eval": eval_gaps,
        })
        save_csv(out_dir / f"bitget_{granularity.lower()}_candles.csv", candles)

        close = candles["close"]
        old = {}
        new = {}
        eval_close = candles.loc[eval_mask, "close"].reset_index(drop=True)
        for span in SPANS[granularity]:
            old_full = ema_v12_old(close, span)
            new_full = ema_sma_seed(close, span)
            v4_full = ema_sma_seed(close, span)
            old_eval = old_full.loc[eval_mask].reset_index(drop=True)
            new_eval = new_full.loc[eval_mask].reset_index(drop=True)
            v4_eval = v4_full.loc[eval_mask].reset_index(drop=True)
            truncated = ema_sma_seed(eval_close, span)
            origin = compare(new_eval, truncated)
            old_new = compare(old_eval, new_eval)
            parity = compare(new_eval, v4_eval)
            first_valid_index = new_eval.first_valid_index()
            first_valid_time = None
            if first_valid_index is not None:
                first_valid_time = candles.loc[eval_mask, "time_utc"].iloc[first_valid_index].isoformat()
            valid_new = new_eval.dropna()
            summaries.append({
                "interval": granularity,
                "ema_span": span,
                "eval_bars": int(len(eval_candles)),
                "valid_ema_bars": int(new_eval.notna().sum()),
                "first_valid_ema_utc": first_valid_time,
                "v12_new_vs_v4": parity,
                "v12_old_vs_v12_new": old_new,
                "full_warmup_vs_eval_only_seed": origin,
                "latest_v12_old": float(old_eval.dropna().iloc[-1]) if old_eval.notna().any() else None,
                "latest_v12_new_v4": float(valid_new.iloc[-1]) if len(valid_new) else None,
            })
            times = candles.loc[eval_mask, "time_utc"].reset_index(drop=True)
            for i, ts in enumerate(times):
                comparison_rows.append({
                    "interval": granularity,
                    "timestamp_utc": ts.isoformat(),
                    "ema_span": span,
                    "v12_old": old_eval.iloc[i],
                    "v12_new_sma_seed": new_eval.iloc[i],
                    "v4_sma_seed_reference": v4_eval.iloc[i],
                    "eval_window_only_seed": truncated.iloc[i],
                })

    report = {
        "symbol": SYMBOL,
        "product_type": PRODUCT_TYPE,
        "data_source": API,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_start_utc": utc_iso(eval_start_ms),
        "evaluation_end_utc": utc_iso(now_ms),
        "warmup_start_utc": utc_iso(fetch_start_ms),
        "interval_coverage": coverage,
        "ema_results": summaries,
        "interpretation": {
            "v12_old": "Pandas EWM adjust=False, recursively seeded by first close; output masked until span bars.",
            "v12_new": "SMA of first span closes, then alpha=2/(span+1) recursive EMA.",
            "v4_reference": "Mirrors V4 assets/js/indicators/ema-v4.js calculateEMA() SMA seed and recurrence.",
            "origin_test": "Compares full pre-window warm-up with EMA re-seeded at the six-month evaluation-window start.",
            "scope": "Bitget futures OHLCV formula comparison; not a direct Bitget chart indicator readout.",
        },
    }

    (out_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "summary.md").write_text(render_markdown(report), encoding="utf-8")
    with (out_dir / "ema_comparison.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(comparison_rows[0].keys()))
        writer.writeheader()
        writer.writerows(comparison_rows)

    print((out_dir / "summary.md").read_text(encoding="utf-8"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
