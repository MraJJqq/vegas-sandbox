import unittest
import numpy as np
import pandas as pd

from scripts.ema_audit import ema_v12_old, ema_sma_seed


def v4_reference(values, span):
    values = list(values)
    if len(values) < span:
        return [np.nan] * len(values)
    out = [np.nan] * (span - 1)
    value = sum(values[:span]) / span
    out.append(value)
    alpha = 2.0 / (span + 1.0)
    for close in values[span:]:
        value = close * alpha + value * (1.0 - alpha)
        out.append(value)
    return out


class EmaAuditTests(unittest.TestCase):
    def test_sma_seed_first_valid_value(self):
        values = pd.Series([10.0, 12.0, 14.0, 16.0])
        result = ema_sma_seed(values, 3)
        self.assertTrue(result.iloc[:2].isna().all())
        self.assertEqual(result.iloc[2], 12.0)

    def test_v12_new_matches_v4_reference_for_all_spans(self):
        values = pd.Series(
            [100.0 + ((i * 17) % 101) / 10.0 + i * 0.003 for i in range(1600)],
            dtype="float64",
        )
        for span in (12, 144, 169, 576, 676):
            expected = np.asarray(v4_reference(values, span), dtype=float)
            actual = ema_sma_seed(values, span).to_numpy()
            np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-12, equal_nan=True)

    def test_old_ewm_and_sma_seed_are_distinct_at_first_valid_bar(self):
        values = pd.Series([100.0 + i * 0.7 + (i % 9) for i in range(100)])
        old = ema_v12_old(values, 12)
        new = ema_sma_seed(values, 12)
        self.assertNotEqual(float(old.iloc[11]), float(new.iloc[11]))

    def test_insufficient_history_has_no_valid_ema(self):
        values = pd.Series([1.0, 2.0, 3.0])
        self.assertTrue(ema_sma_seed(values, 4).isna().all())


if __name__ == "__main__":
    unittest.main()
