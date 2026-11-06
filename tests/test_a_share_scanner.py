import unittest
import pandas as pd
from scripts.a_share_scanner import confirmation_side, ema, evaluate, signal_sort_key

class AShareScannerTests(unittest.TestCase):
    def test_ema_warmup(self):
        result = ema(pd.Series([1.0] * 676), 676)
        self.assertEqual(result.notna().sum(), 1)
        self.assertEqual(result.iloc[-1], 1.0)

    def test_short_history_not_scannable(self):
        df = pd.DataFrame({"close":[1.0]*675,"high":[1.0]*675,"low":[1.0]*675,"amount":[1.0]*675,"tradestatus":[1]*675,"date":pd.date_range("2024-01-01",periods=675)})
        result, reason = evaluate("sh.600519", "贵州茅台", df, "2025-01-01")
        self.assertIsNone(result)
        self.assertEqual(reason, "insufficient_history")

    def test_confirmation_side(self):
        self.assertEqual(confirmation_side(101,100), "上方")
        self.assertEqual(confirmation_side(99,100), "下方")
        self.assertIsNone(confirmation_side(100,100))

    def test_touch_then_later_close_confirms_once(self):
        dates = pd.date_range("2024-01-01", periods=678)
        df = pd.DataFrame({"date":dates,"close":[100.0]*677+[105.0],"high":[100.0]*676+[100.2,106.0],"low":[100.0]*676+[99.8,104.0],"amount":[1000000.0]*678,"tradestatus":[1]*678})
        result, reason = evaluate("sh.600519", "贵州茅台", df, dates[676].date().isoformat())
        self.assertEqual(reason,"ok")
        self.assertEqual(len(result["signals"]),1)
        self.assertEqual(result["signals"][0]["confirmation_side"],"上方")

    def test_signal_sort_uses_existing_fields(self):
        a={"confirmation_date":"2026-01-02","code":"sh.600519","observation_date":"2026-01-01"}
        b={"confirmation_date":"2026-01-01","code":"sz.000001","observation_date":"2025-12-31"}
        self.assertLess(signal_sort_key(b),signal_sort_key(a))

if __name__ == "__main__":
    unittest.main()
