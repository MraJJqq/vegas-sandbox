import unittest

import numpy as np
import pandas as pd

from scripts.baostock_daily_audit import ema_sma_seed


class BaostockDailyAuditTests(unittest.TestCase):
    def test_sma_seed_and_recursive_update(self):
        values = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0])
        result = ema_sma_seed(values, 3)
        self.assertTrue(result.iloc[:2].isna().all())
        self.assertAlmostEqual(result.iloc[2], 12.0)
        alpha = 2.0 / 4.0
        self.assertAlmostEqual(result.iloc[3], 16.0 * alpha + 12.0 * (1.0 - alpha))

    def test_longest_vegas_ema_requires_sufficient_daily_bars(self):
        values = pd.Series(np.linspace(10.0, 20.0, 675))
        self.assertTrue(ema_sma_seed(values, 676).isna().all())
        values = pd.concat([values, pd.Series([20.1])], ignore_index=True)
        result = ema_sma_seed(values, 676)
        self.assertEqual(int(result.notna().sum()), 1)

    def test_invalid_span_rejected(self):
        with self.assertRaises(ValueError):
            ema_sma_seed(pd.Series([1.0]), 0)


if __name__ == "__main__":
    unittest.main()
