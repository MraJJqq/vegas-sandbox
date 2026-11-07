import unittest

from scripts.binance_um_data import BinanceUMClient, BinanceAccessError, ema


class FakeResponse:
    status_code = 200
    ok = True
    text = ""

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.last_url = url
        self.last_params = params
        return FakeResponse(self.payload)


class BinanceClientTests(unittest.TestCase):
    def test_ema_sma_seed_and_recurrence(self):
        values = ema([1, 2, 3, 4, 5], 3)
        self.assertIsNone(values[0])
        self.assertIsNone(values[1])
        self.assertAlmostEqual(values[2], 2.0)
        self.assertAlmostEqual(values[3], 3.0)
        self.assertAlmostEqual(values[4], 4.0)

    def test_native_eight_hour_interval_is_passed_to_binance(self):
        row = [0, "100", "110", "90", "105", "12", 28_799_999,
               "1200", 10, "6", "600", "0"]
        session = FakeSession([row])
        candles = BinanceUMClient(session=session).klines("BTCUSDT", "8h", 1)
        self.assertEqual(session.last_params["interval"], "8h")
        self.assertEqual(candles[0]["close"], 105.0)
        self.assertEqual(candles[0]["open_time"], 0)

    def test_invalid_interval_is_rejected(self):
        client = BinanceUMClient(session=FakeSession([]))
        with self.assertRaises(ValueError):
            client.klines("BTCUSDT", "8H", 10)

    def test_http_451_is_reported_as_regional_restriction(self):
        class RestrictedResponse(FakeResponse):
            status_code = 451
            ok = False
            text = "Unavailable for legal reasons"

        class RestrictedSession(FakeSession):
            def get(self, url, params=None, timeout=None):
                return RestrictedResponse({})

        client = BinanceUMClient(session=RestrictedSession({}))
        with self.assertRaises(BinanceAccessError) as caught:
            client.ping()
        self.assertEqual(caught.exception.status_code, 451)
        self.assertIn("region", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
