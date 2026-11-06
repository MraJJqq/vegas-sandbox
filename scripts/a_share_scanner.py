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
REQUEST_RETRIES = 4
REQUEST_BACKOFF_SECONDS = 0.75
REQUEST_INTERVAL_SECONDS = 0.12


def frame_from_rs(rs):
    if rs.error_code != "0":
        raise RuntimeError(f"Baostock {rs.error_code}: {rs.error_msg}")
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    return pd.DataFrame(rows, columns=rs.fields)


def retry_request(request, *, retries=REQUEST_RETRIES, sleep=time.sleep):
    """Retry transient Baostock request failures with bounded exponential backoff."""
    last_error = None
    for attempt in range(retries + 1):
        try:
            result = request()
            sleep(REQUEST_INTERVAL_SECONDS)
            return result
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                break
            delay = REQUEST_BACKOFF_SECONDS * (2 ** attempt)
            print(
                f"Baostock request failed ({attempt + 1}/{retries + 1}); "
                f"retrying in {delay:.2f}s: {str(exc)[:180]}",
                flush=True,
            )
            sleep(delay)
    raise last_error


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
    stocks = retry_request(lambda: frame_from_rs(bs.query_all_stock(day)))
    if stocks.empty:
        raise RuntimeError("Baostock returned no stock universe")
    required = {"code", "tradeStatus", "code_name"}
    missing = required.difference(stocks.columns)
    if missing:
        raise RuntimeError(f"Baostock stock list missing fields: {sorted(missing)}")
    stocks["code"] = stocks["code"].astype(str)
    stocks["code_name"] = stocks["code_name"].fillna("").astype(str)
    stocks = stocks[
        stocks["code"].str.startswith(A_SHARE_PREFIXES)
        & (stocks["tradeStatus"].astype(str) == "1")
    ].copy()
    stocks = stocks[~stocks["code_name"].str.contains("ST|退", case=False, na=False)]
    return stocks.drop_duplicates("code").sort_values("code").reset_index(drop=True)


def confirmation_side(close, ema12):
    """Return the EMA12 side for a completed daily close; equality is unconfirmed."""
    if close > ema12:
        return "上方"
    if close < ema12:
        return "下方"
    return None


def signal_sort_key(signal):
    return (signal["confirmation_date"], signal["code"], signal["observation_date"])


def daily_bars(code, start, end):
    df = retry_request(lambda: frame_from_rs(bs.query_history_k_data_plus(
        code, FIELDS, start_date=start, end_date=end,
        frequency="d", adjustflag="2"
    )))
    if df.empty:
        return df
    for c in ("open", "high", "low", "close", "volume", "amount", "tradestatus"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.sort_values("date").drop_duplicates("date").reset_index(drop=True)


def evaluate(code, name, df, scan_start, scan_end=None):
    full = df[(df["tradestatus"] == 1) & df["close"].gt(0)
              & df["high"].gt(0) & df["low"].gt(0)].copy()
    full = full.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    if len(full) < 676:
        return None, "insufficient_history"

    # Compute EMAs over the entire fetched history. Keep the untrimmed price
    # history for liquidity and true trailing-365-calendar-day return ranking.
    for span in EMA_SPANS:
        full[f"ema{span}"] = ema(full["close"], span)
    ema_ready = full.dropna(subset=[f"ema{x}" for x in EMA_SPANS]).reset_index(drop=True)
    if ema_ready.empty:
        return None, "ema_not_ready"

    start_ts = pd.Timestamp(scan_start)
    end_ts = pd.Timestamp(scan_end) if scan_end is not None else full["date"].max()
    scan = ema_ready[(ema_ready["date"] >= start_ts) & (ema_ready["date"] <= end_ts)]
    if scan.empty:
        return None, "no_ema_ready_scan_bars"

    signals = []
    pending_zone = None
    for _, row in scan.iterrows():
        touched = []
        for label, x, y in (("中锋", 144, 169), ("红峰", 576, 676)):
            lo = min(row[f"ema{x}"], row[f"ema{y}"])
            hi = max(row[f"ema{x}"], row[f"ema{y}"])
            if row["low"] <= hi and row["high"] >= lo:
                touched.append(label)
        if touched:
            pending_zone = {"date": row["date"].date().isoformat(), "zones": touched}
            continue
        if pending_zone is not None:
            side = confirmation_side(float(row["close"]), float(row["ema12"]))
            if side is None:
                continue
            signals.append({
                "observation_date": pending_zone["date"],
                "confirmation_date": row["date"].date().isoformat(),
                "code": code, "name": name,
                "close": round(float(row["close"]), 4),
                "ema12": round(float(row["ema12"]), 4),
                "observation_zone": ",".join(pending_zone["zones"]),
                "close_vs_ema12": side,
                "confirmation_side": side,
            })
            pending_zone = None

    # Ranking metrics use the full price series, not the EMA676-trimmed tail.
    recent20 = full.tail(20)
    amount = float(recent20["amount"].median()) if len(recent20) else 0.0
    one_year_ago = end_ts - pd.Timedelta(days=365)
    base = full[full["date"] <= one_year_ago]
    if base.empty:
        return None, "insufficient_one_year_history"
    latest_close = float(full.iloc[-1]["close"])
    base_close = float(base.iloc[-1]["close"])
    ret = latest_close / base_close - 1.0
    return {
        "code": code, "name": name, "signals": signals,
        "median_amount_20d": amount, "return_1y": ret,
        "last_date": full["date"].iloc[-1].date().isoformat(),
        "history_bars": len(full),
        "ema_ready_bars": len(ema_ready),
        "scan_bars": len(scan),
    }, "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=3,
                    help="EMA warm-up history in years before the scan window")
    ap.add_argument("--universe-size", type=int, default=2000)
    ap.add_argument("--scan-days", type=int, default=365)
    ap.add_argument("--out", default="results/a-share-scan")
    args = ap.parse_args()
    if args.years < 3 or args.scan_days < 1 or args.universe_size < 1:
        ap.error("--years must be >= 3; --scan-days and --universe-size must be positive")

    end = date.today()
    scan_start = end - timedelta(days=args.scan_days)
    # Fetch warm-up history PLUS the independent scan window.
    start = scan_start - timedelta(days=365 * args.years + 15)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"Baostock login failed: {login.error_code} {login.error_msg}")
    try:
        stocks = stock_list(end.isoformat())
        evaluated, failures = [], []
        total = len(stocks)
        for n, row in stocks.iterrows():
            code, name = row["code"], row["code_name"]
            try:
                df = daily_bars(code, start.isoformat(), end.isoformat())
                if df.empty:
                    failures.append({"code": code, "name": name, "reason": "empty"})
                    continue
                result, status = evaluate(
                    code, name, df, scan_start.isoformat(), end.isoformat()
                )
                if result:
                    evaluated.append(result)
                else:
                    failures.append({"code": code, "name": name, "reason": status})
            except Exception as exc:
                failures.append({"code": code, "name": name, "reason": str(exc)[:240]})
            if (n + 1) % 100 == 0 or n + 1 == total:
                print(
                    f"processed {n+1}/{total}; eligible={len(evaluated)}; "
                    f"errors={len(failures)}",
                    flush=True,
                )

        ranked = sorted(
            evaluated,
            key=lambda x: (np.log1p(max(0.0, x["median_amount_20d"]))
                           * (1.0 + max(-0.5, min(1.5, x["return_1y"])))),
            reverse=True,
        )
        selected = ranked[:args.universe_size]
        signals = [s for stock in selected for s in stock["signals"]]
        signals.sort(key=signal_sort_key)
        reason_counts = {}
        for item in failures:
            reason = item["reason"].split(":")[0]
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

        summary = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": "Baostock", "market": "沪深A股", "frequency": "1D",
            "warmup_years": args.years, "scan_window_days": args.scan_days,
            "history_start": start.isoformat(), "scan_start": scan_start.isoformat(),
            "scan_end": end.isoformat(),
            "requested_universe_size": args.universe_size,
            "listed_active_candidates": total,
            "history_eligible": len(evaluated),
            "selected_universe_size": len(selected),
            "universe_target_met": len(selected) == args.universe_size,
            "failed_or_insufficient": len(failures),
            "failure_reason_counts": reason_counts,
            "signal_count": len(signals),
            "signals": signals,
            "selection_method": "active non-ST Shanghai/Shenzhen A-shares; rank by 20-session median turnover and true trailing-365-calendar-day return",
            "signal_rule": "daily bar touches EMA144/169 or EMA576/676 area; a later non-touch daily close strictly above/below EMA12 confirms; equality remains pending",
            "limitations": [
                "Baostock industry classifications are not used as a reliable real-time hot-sector feed.",
                "Universe ranking uses turnover and trailing trend as a reproducible proxy for representative hot/trending names.",
                "If fewer than the requested 2000 stocks have complete data, the report states the shortfall rather than padding the universe.",
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
