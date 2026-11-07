import unittest
from unittest.mock import Mock, patch
import pandas as pd

from scripts.a_share_scanner import (
    confirmation_side, ema, evaluate, retry_request, signal_sort_key, stock_list
)


class AShareScannerTests(unittest.TestCase):
    def make_frame(self, count=1100):
        dates = pd.bdate_range("2022-01-03", periods=count)
        close = [100.0 + i * 0.01 for i in range(count)]
        return pd.DataFrame({
            "date": dates, "close": close,
            "high": [x + 0.5 for x in close],
            "low": [x - 0.5 for x in close],
            "amount": [1_000_000.0 + i for i in range(count)],
            "tradestatus": [1] * count,
        })

    def test_ema_warmup(self):
        result = ema(pd.Series([1.0] * 676), 676)
        self.assertEqual(result.notna().sum(), 1)
        self.assertEqual(result.iloc[-1], 1.0)

    def test_short_history_not_scannable(self):
        df = self.make_frame(675)
        result, reason = evaluate("sh.600519", "贵州茅台", df, "2025-01-01")
        self.assertIsNone(result)
        self.assertEqual(reason, "insufficient_history")

    def test_confirmation_side(self):
        self.assertEqual(confirmation_side(101, 100), "上方")
        self.assertEqual(confirmation_side(99, 100), "下方")
        self.assertIsNone(confirmation_side(100, 100))

    def test_touch_then_later_close_confirms_once(self):
        dates = pd.bdate_range("2022-01-03", periods=678)
        close = [100.0] * 677 + [105.0]
        df = pd.DataFrame({
            "date": dates, "close": close,
            "high": [100.0] * 676 + [100.2, 106.0],
            "low": [100.0] * 676 + [99.8, 104.0],
            "amount": [1_000_000.0] * 678,
            "tradestatus": [1] * 678,
        })
        result, reason = evaluate(
            "sh.600519", "贵州茅台", df, dates[676].date().isoformat()
        )
        self.assertEqual(reason, "ok")
        self.assertEqual(len(result["signals"]), 1)
        self.assertEqual(result["signals"][0]["confirmation_side"], "上方")

    def test_true_one_year_return_uses_untrimmed_history(self):
        df = self.make_frame(1100)
        end = df["date"].iloc[-1]
        result, reason = evaluate(
            "sh.600519", "贵州茅台", df,
            (end - pd.Timedelta(days=365)).date().isoformat(),
            end.date().isoformat(),
        )
        self.assertEqual(reason, "ok")
        expected_base = df[df["date"] <= end - pd.Timedelta(days=365)].iloc[-1]["close"]
        self.assertAlmostEqual(
            result["return_1y"], df.iloc[-1]["close"] / expected_base - 1.0
        )
        self.assertGreater(result["history_bars"], result["ema_ready_bars"])
        self.assertGreater(result["scan_bars"], 150)

    def test_scan_window_is_independent_of_ema_warmup(self):
        df = self.make_frame(1100)
        end = df["date"].iloc[-1]
        start = end - pd.Timedelta(days=365)
        result, reason = evaluate(
            "sh.600519", "贵州茅台", df, start.date().isoformat(), end.date().isoformat()
        )
        self.assertEqual(reason, "ok")
        self.assertGreaterEqual(result["scan_bars"], 150)

    def test_retry_request_recovers_after_transient_failure(self):
        request = Mock(side_effect=[RuntimeError("10002007"), "ok"])
        sleeps = []
        result = retry_request(request, retries=2, sleep=sleeps.append)
        self.assertEqual(result, "ok")
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(sleeps), 2)

    def test_retry_request_stops_after_limit(self):
        request = Mock(side_effect=RuntimeError("network"))
        with self.assertRaisesRegex(RuntimeError, "network"):
            retry_request(request, retries=2, sleep=lambda _: None)
        self.assertEqual(request.call_count, 3)

    def test_stock_list_retries_empty_response(self):
        empty = pd.DataFrame(columns=["code", "tradeStatus", "code_name"])
        valid = pd.DataFrame([{
            "code": "sh.600519", "tradeStatus": "1", "code_name": "贵州茅台"
        }])
        sleeps = []
        with patch("scripts.a_share_scanner.bs.query_all_stock", return_value=object()) as query, \
             patch("scripts.a_share_scanner.frame_from_rs", side_effect=[empty, empty, valid]), \
             patch("scripts.a_share_scanner.retry_request", side_effect=lambda request: request()):
            result = stock_list("2026-11-07", empty_retries=2, sleep=sleeps.append)
        self.assertEqual(result["code"].tolist(), ["sh.600519"])
        self.assertEqual(query.call_count, 3)
        self.assertEqual([call.args[0] for call in query.call_args_list], ["2026-11-07"] * 3)
        self.assertEqual(sleeps, [0.75, 1.5])

    def test_stock_list_falls_back_to_previous_date(self):
        empty = pd.DataFrame(columns=["code", "tradeStatus", "code_name"])
        valid = pd.DataFrame([{
            "code": "sz.000001", "tradeStatus": "1", "code_name": "平安银行"
        }])
        responses = [empty, empty, empty, empty, valid]
        queried_dates = []

        def query(day):
            queried_dates.append(day)
            return object()

        with patch("scripts.a_share_scanner.bs.query_all_stock", side_effect=query), \
             patch("scripts.a_share_scanner.frame_from_rs", side_effect=responses), \
             patch("scripts.a_share_scanner.retry_request", side_effect=lambda request: request()):
            result = stock_list(
                "2026-11-07", empty_retries=3, fallback_days=5, sleep=lambda _: None
            )
        self.assertEqual(result["code"].tolist(), ["sz.000001"])
        self.assertEqual(queried_dates, ["2026-11-07"] * 4 + ["2026-11-06"])

    def test_stock_list_fails_clearly_after_empty_fallback_window(self):
        empty = pd.DataFrame(columns=["code", "tradeStatus", "code_name"])
        with patch("scripts.a_share_scanner.bs.query_all_stock", return_value=object()), \
             patch("scripts.a_share_scanner.frame_from_rs", return_value=empty), \
             patch("scripts.a_share_scanner.retry_request", side_effect=lambda request: request()):
            with self.assertRaisesRegex(RuntimeError, "previous 2 calendar days"):
                stock_list(
                    "2026-11-07", empty_retries=1, fallback_days=2, sleep=lambda _: None
                )

    def test_signal_sort_uses_existing_fields(self):
        a = {"confirmation_date": "2026-01-02", "code": "sh.600519", "observation_date": "2026-01-01"}
        b = {"confirmation_date": "2026-01-01", "code": "sz.000001", "observation_date": "2025-12-31"}
        self.assertLess(signal_sort_key(b), signal_sort_key(a))


if __name__ == "__main__":
    unittest.main()
