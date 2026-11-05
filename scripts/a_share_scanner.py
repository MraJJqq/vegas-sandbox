from __future__ import annotations

import argparse
import json
import time
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

import baostock as bs
import numpy as np
import pandas as pd

EMA_SPANS = (12, 144, 169, 576, 676)
FIELDS = "date,code,open,high,low,close,volume,amount,tradestatus,isST"
A_SHARE_PREFIXES = ("sh.60", "sh.68", "sz.00", "sz.30")


def frame_from_rs(rs):
    if rs.error_code != "0":
        raise RuntimeError(f"Baostock {rs.error_code}: {rs.error_msg}")
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    return pd.DataFrame(rows, columns=rs.fields)


def ema(values, span):
    a = values.to_numpy(dtype=float)
    out = np.full(len(a), np.nan)
    if len(a) < span:
        return pd.Series(out, index=values.index)
    alpha = 2.0 / (span + 1.0)
    current = float(np.mean(a[:span]))
    out[span - 1] = current
    for i in range(span, len(a)):
        current = alpha * a[i] + (1.0 - alpha) * current
        out[i] = current
    return pd.Series(out, index=values.index)


def stock_list(day):
    rs = bs.query_all_stock(day)
    stocks = frame_from_rs(rs)
    if stocks.empty:
        raise RuntimeError("Baostock returned no stock universe")
    stocks = stocks[
        stocks["code"].str.startswith(A_SHARE_PREFIXES)
        & (stocks["tradeStatus"].astype(str) == "1")
    ].copy()
    stocks = stocks[~stocks["code_name"].str.contains("ST|退", case=False, na=False)]
    return stocks.drop_duplicates("code").sort_values("code").reset_index(drop=True)


def daily_bars(code, start, end):
    rs = bs.query_history_k_data_plus(
        code, FIELDS, start_date=start, end_date=end,
        frequency="d", adjustflag="2"
    )
    df = frame_from_rs(rs)
    if df.empty:
        return df
    for c in ("open", "high", "low", "close", "volume", "amount", "tradestatus"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.sort_values("date").drop_duplicates("date").reset_index(drop=True)


def evaluate(code, name, df, scan_start):
    valid = df[(df["tradestatus"] == 1) & df["close"].gt(0)
               & df["high"].gt(0) & df["low"].gt(0)].copy().reset_index(drop=True)
    if len(valid) < 676:
        return None, "insufficient_history"
    for span in EMA_SPANS:
        valid[f"ema{span}"] = ema(valid["close"], span)
    valid = valid.dropna(subset=[f"ema{x}" for x in EMA_SPANS]).reset_index(drop=True)
    if len(valid) < 2:
        return None, "ema_not_ready"

    # A formal signal requires a Vegas-zone touch on an earlier daily bar,
    # followed by a later daily close on either side of EMA12.
    signals = []
    start_ts = pd.Timestamp(scan_start)
    eligible = valid.index[valid["date"] >= start_ts].tolist()
    for i in eligible:
        if i < 1:
            continue
        row = valid.iloc[i]
        prior = valid.iloc[:i]
        zone_touches = []
        for label, x, y in (("中锋", 144, 169), ("红峰", 576, 676)):
            lo = min(row[f"ema{x}"], row[f"ema{y}"])
            hi = max(row[f"ema{x}"], row[f"ema{y}"])
            if row["low"] <= hi and row["high"] >= lo:
                zone_touches.append(label)
        if not zone_touches:
            continue
        # Require a prior candle's touch; today's touch cannot confirm itself.
        prior_touch = False
        for _, p in prior.iterrows():
            for x, y in ((144, 169), (576, 676)):
                lo = min(p[f"ema{x}"], p[f"ema{y}"])
                hi = max(p[f"ema{x}"], p[f"ema{y}"])
                if p["low"] <= hi and p["high"] >= lo:
                    prior_touch = True
                    break
            if prior_touch:
                break
        if prior_touch:
            signals.append({
                "date": row["date"].date().isoformat(),
                "code": code, "name": name,
                "close": round(float(row["close"]), 4),
                "ema12": round(float(row["ema12"]), 4),
                "observation_zone": ",".join(zone_touches),
                "close_vs_ema12": "上方" if row["close"] > row["ema12"] else "下方",
            })
    # Rank quality for universe selection using recent traded value and 1y return.
    recent = valid.tail(250)
    amount = float(recent["amount"].tail(20).median()) if "amount" in recent else 0.0
    ret = float(recent["close"].iloc[-1] / recent["close"].iloc[0] - 1.0)
    return {
        "code": code, "name": name, "signals": signals,
        "median_amount_20d": amount, "return_1y": ret,
        "last_date": valid["date"].iloc[-1].date().isoformat(),
        "bars": len(valid),
    }, "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--universe-size", type=int, default=2000)
    ap.add_argument("--scan-days", type=int, default=365)
    ap.add_argument("--out", default="results/a-share-scan")
    args = ap.parse_args()
    end = date.today()
    start = end - timedelta(days=365 * args.years + 10)
    scan_start = end - timedelta(days=args.scan_days)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"Baostock login failed: {login.error_code} {login.error_msg}")
    try:
        stocks = stock_list(end.isoformat())
        # Fetch 3y histories for active A-share names, then rank by liquidity/trend.
        evaluated, failures = [], []
        total = len(stocks)
        for n, row in stocks.iterrows():
            code, name = row["code"], row["code_name"]
            try:
                df = daily_bars(code, start.isoformat(), end.isoformat())
                if df.empty:
                    failures.append({"code": code, "name": name, "reason": "empty"})
                    continue
                result, status = evaluate(code, name, df, scan_start)
                if result:
                    evaluated.append(result)
                else:
                    failures.append({"code": code, "name": name, "reason": status})
            except Exception as exc:
                failures.append({"code": code, "name": name, "reason": str(exc)[:240]})
            if (n + 1) % 100 == 0:
                print(f"processed {n+1}/{total}; eligible={len(evaluated)}; errors={len(failures)}", flush=True)

        # Trend/liquidity score; the pool is deterministic and fully auditable.
        ranked = sorted(
            evaluated,
            key=lambda x: (np.log1p(max(0.0, x["median_amount_20d"]))
                           * (1.0 + max(-0.5, min(1.5, x["return_1y"])))),
            reverse=True,
        )
        selected = ranked[:args.universe_size]
        signals = [s for stock in selected for s in stock["signals"]]
        signals.sort(key=lambda x: (x["date"], x["code"]))
        summary = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": "Baostock", "market": "沪深A股", "frequency": "1D",
            "warmup_years": args.years, "scan_window_days": args.scan_days,
            "requested_universe_size": args.universe_size,
            "listed_active_candidates": total,
            "three_year_history_eligible": len(evaluated),
            "selected_universe_size": len(selected),
            "failed_or_insufficient": len(failures),
            "signal_count": len(signals),
            "signals": signals,
            "selection_method": "active non-ST Shanghai/Shenzhen A-shares; rank by 20-session median turnover and trailing one-year return",
            "signal_rule": "previous daily bar touches EMA144/169 or EMA576/676 area; a later daily close confirms relative to EMA12",
            "limitations": [
                "Baostock industry classifications are not used as a reliable real-time hot-sector feed.",
                "Universe ranking uses turnover and trailing trend as a reproducible proxy for representative hot/trending names.",
                "Signal list is computed on selected top-ranked universe; the scan window is trailing one year.",
            ],
        }
        (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        pd.DataFrame(selected).drop(columns=["signals"], errors="ignore").to_csv(out / "universe.csv", index=False)
        pd.DataFrame(signals).to_csv(out / "signals.csv", index=False)
        pd.DataFrame(failures).to_csv(out / "failures.csv", index=False)
        print(json.dumps({k:v for k,v in summary.items() if k != "signals"}, ensure_ascii=False, indent=2), flush=True)
        print("SIGNALS=" + json.dumps(signals, ensure_ascii=False), flush=True)
    finally:
        bs.logout()


if __name__ == "__main__":
    main()
