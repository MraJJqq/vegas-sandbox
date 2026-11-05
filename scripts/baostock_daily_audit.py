from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import baostock as bs
import numpy as np
import pandas as pd

CODE = "sh.600519"
EMA_SPANS = (12, 144, 169, 576, 676)
FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,"
    "adjustflag,turn,tradestatus,pctChg,isST"
)


def rows_to_frame(rs) -> pd.DataFrame:
    if rs.error_code != "0":
        raise RuntimeError(f"Baostock API error {rs.error_code}: {rs.error_msg}")
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    return pd.DataFrame(rows, columns=rs.fields)


def query_daily(code: str, start: str, end: str, adjustflag: str) -> pd.DataFrame:
    rs = bs.query_history_k_data_plus(
        code,
        FIELDS,
        start_date=start,
        end_date=end,
        frequency="d",
        adjustflag=adjustflag,
    )
    frame = rows_to_frame(rs)
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    numeric = ("open", "high", "low", "close", "preclose", "volume", "amount", "tradestatus")
    for col in numeric:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame.sort_values("date").reset_index(drop=True)


def ema_sma_seed(values: pd.Series, span: int) -> pd.Series:
    arr = values.to_numpy(dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)
    valid = np.isfinite(arr)
    if not valid.all():
        raise ValueError("EMA input must contain only valid trading-session closes")
    if len(arr) < span:
        return pd.Series(out, index=values.index, name=f"ema{span}")
    alpha = 2.0 / (span + 1.0)
    current = float(np.mean(arr[:span]))
    out[span - 1] = current
    for i in range(span, len(arr)):
        current = arr[i] * alpha + current * (1.0 - alpha)
        out[i] = current
    return pd.Series(out, index=values.index, name=f"ema{span}")


def query_calendar(start: str, end: str) -> pd.DataFrame:
    rs = bs.query_trade_dates(start_date=start, end_date=end)
    frame = rows_to_frame(rs)
    if frame.empty:
        return frame
    frame["calendar_date"] = pd.to_datetime(frame["calendar_date"], errors="coerce")
    frame["is_trading_day"] = frame["is_trading_day"].astype(str)
    return frame


def query_factors(code: str, start: str, end: str) -> pd.DataFrame:
    rs = bs.query_adjust_factor(code=code, start_date=start, end_date=end)
    frame = rows_to_frame(rs)
    if not frame.empty:
        frame["dividOperateDate"] = pd.to_datetime(frame["dividOperateDate"], errors="coerce")
        for col in ("foreAdjustFactor", "backAdjustFactor", "adjustFactor"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame


def build_report(raw: pd.DataFrame, adjusted: pd.DataFrame, calendar: pd.DataFrame,
                 factors: pd.DataFrame, start: str, end: str, eval_days: int) -> tuple[dict, pd.DataFrame]:
    if raw.empty or adjusted.empty:
        raise RuntimeError("Baostock returned an empty raw or forward-adjusted daily series")

    duplicates_raw = int(raw["date"].duplicated().sum())
    duplicates_adj = int(adjusted["date"].duplicated().sum())
    raw_dates = set(raw["date"].dropna())
    adj_dates = set(adjusted["date"].dropna())
    date_mismatch = sorted(raw_dates.symmetric_difference(adj_dates))

    expected = set(calendar.loc[calendar["is_trading_day"] == "1", "calendar_date"].dropna())
    returned = raw_dates
    missing_calendar_rows = sorted(expected - returned)
    unexpected_rows = sorted(returned - expected)

    valid = raw.loc[
        (raw["tradestatus"] == 1) & raw["close"].notna() & (raw["close"] > 0)
    ].copy()
    valid_adj = adjusted.loc[
        (adjusted["tradestatus"] == 1) & adjusted["close"].notna() & (adjusted["close"] > 0)
    ].copy()

    raw_valid_dates = set(valid["date"])
    adj_valid_dates = set(valid_adj["date"])
    common = sorted(raw_valid_dates & adj_valid_dates)
    raw_by_date = valid.set_index("date")
    adj_by_date = valid_adj.set_index("date")
    raw_close = raw_by_date.loc[common, "close"].astype(float)
    adj_close = adj_by_date.loc[common, "close"].astype(float)
    ratio = (adj_close / raw_close).replace([np.inf, -np.inf], np.nan).dropna()

    ema_frame = valid[["date", "close"]].copy().reset_index(drop=True)
    ema_rows = []
    eval_cutoff = pd.Timestamp(end) - pd.Timedelta(days=eval_days)
    for span in EMA_SPANS:
        series = ema_sma_seed(ema_frame["close"], span)
        ema_frame[f"ema{span}"] = series
        eval_valid = series.loc[ema_frame["date"] >= eval_cutoff].dropna()
        ema_rows.append({
            "span": span,
            "total_valid": int(series.notna().sum()),
            "valid_in_eval_window": int(len(eval_valid)),
            "latest_value": float(series.dropna().iloc[-1]) if series.notna().any() else None,
            "first_valid_date": (
                ema_frame.loc[series.first_valid_index(), "date"].date().isoformat()
                if series.notna().any() else None
            ),
        })

    eval_bars = int((valid["date"] >= eval_cutoff).sum())
    ratio_stats = {
        "matched_price_rows": int(len(common)),
        "adjusted_to_raw_ratio_min": float(ratio.min()) if len(ratio) else None,
        "adjusted_to_raw_ratio_max": float(ratio.max()) if len(ratio) else None,
        "ratio_change_points": int((ratio.diff().abs() > 1e-10).sum()) if len(ratio) else 0,
    }

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Baostock",
        "symbol": CODE,
        "period": {"start": start, "end": end, "evaluation_days": eval_days},
        "history": {
            "raw_rows": int(len(raw)),
            "forward_adjusted_rows": int(len(adjusted)),
            "valid_trading_bars": int(len(valid)),
            "evaluation_window_valid_bars": eval_bars,
            "first_date": raw["date"].min().date().isoformat(),
            "last_date": raw["date"].max().date().isoformat(),
            "duplicate_raw_dates": duplicates_raw,
            "duplicate_adjusted_dates": duplicates_adj,
            "raw_adjusted_date_mismatch_count": len(date_mismatch),
        },
        "calendar_integrity": {
            "expected_market_sessions": len(expected),
            "returned_dates": len(returned),
            "missing_session_rows": len(missing_calendar_rows),
            "missing_session_dates_sample": [d.date().isoformat() for d in missing_calendar_rows[:30]],
            "unexpected_dates": len(unexpected_rows),
            "suspended_rows": int((raw["tradestatus"] == 0).sum()),
            "rows_with_missing_or_nonpositive_close": int((raw["close"].isna() | (raw["close"] <= 0)).sum()),
        },
        "corporate_actions_and_adjustment": {
            "adjustment_factor_events": int(len(factors)),
            "events": [
                {
                    "date": row["dividOperateDate"].date().isoformat(),
                    "forward_factor": float(row["foreAdjustFactor"]),
                    "backward_factor": float(row["backAdjustFactor"]),
                }
                for _, row in factors.iterrows()
                if pd.notna(row["dividOperateDate"])
            ],
            **ratio_stats,
            "note": (
                "Forward-adjusted and raw close series are compared by date. "
                "Adjustment-factor events are reported separately; this is not an independent-vendor parity test."
            ),
        },
        "ema": ema_rows,
        "readiness": {
            "ema676_available": bool(ema_rows[-1]["total_valid"] > 0),
            "duplicate_free": duplicates_raw == 0 and duplicates_adj == 0,
            "raw_adjusted_dates_match": len(date_mismatch) == 0,
            "full_market_calendar_coverage": len(missing_calendar_rows) == 0,
            "status": "REVIEW_REQUIRED",
        },
        "limitations": [
            "One representative stock only: sh.600519 (贵州茅台).",
            "iTick cross-vendor comparison is not included because no iTick API token was supplied.",
            "A five-year history is used to give EMA676 a substantial warm-up; the six-month window is separately reported.",
            "Baostock daily data update time may affect the newest trading date; do not treat a same-day missing row before publication as a permanent gap.",
        ],
    }
    checks = report["readiness"]
    checks["status"] = (
        "PASS" if checks["ema676_available"] and checks["duplicate_free"]
        and checks["raw_adjusted_dates_match"] and checks["full_market_calendar_coverage"]
        else "REVIEW_REQUIRED"
    )
    return report, ema_frame


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", default=CODE)
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--evaluation-days", type=int, default=184)
    parser.add_argument("--out", default="results/baostock-a-share")
    args = parser.parse_args()

    end_date = date.today()
    start_date = end_date - timedelta(days=365 * args.years + 3)
    start, end = start_date.isoformat(), end_date.isoformat()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"Baostock login failed: {login.error_code} {login.error_msg}")
    try:
        print(f"Fetching {args.code}: {start} to {end}", flush=True)
        raw = query_daily(args.code, start, end, "3")
        adjusted = query_daily(args.code, start, end, "2")
        calendar = query_calendar(start, end)
        factors = query_factors(args.code, start, end)
        report, ema_frame = build_report(
            raw, adjusted, calendar, factors, start, end, args.evaluation_days
        )
        raw.to_csv(out / "daily_unadjusted.csv", index=False)
        adjusted.to_csv(out / "daily_forward_adjusted.csv", index=False)
        factors.to_csv(out / "adjustment_factors.csv", index=False)
        ema_frame.to_csv(out / "ema_series.csv", index=False, float_format="%.12f")
        (out / "summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        return 0
    finally:
        bs.logout()


if __name__ == "__main__":
    raise SystemExit(main())
