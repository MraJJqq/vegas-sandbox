import unittest
import pandas as pd
from scripts.a_share_scanner import ema, evaluate


class AShareScannerTests(unittest.TestCase):
    def test_ema_warmup(self):
        values = pd.Series([1.0] * 676)
        result = ema(values, 676)
        self.assertEqual(result.notna().sum(), 1)
        self.assertEqual(result.iloc[-1], 1.0)

    def test_short_history_not_scannable(self):
        df = pd.DataFrame({"close":[1.0]*675,"high":[1.0]*675,"low":[1.0]*675,
                           "amount":[1.0]*675,"tradestatus":[1]*675,
                           "date":pd.date_range("2024-01-01",periods=675)})
        result, reason = evaluate("sh.600519","贵州茅台",df,"2025-01-01")
        self.assertIsNone(result)
        self.assertEqual(reason,"insufficient_history")


if __name__ == "__main__":
    unittest.main()
