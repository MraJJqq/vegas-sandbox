import unittest
from prototypes.bark_idempotency import delivery_identity

class BarkIdentityTests(unittest.TestCase):
    def setUp(self):
        self.report = {"signal_day": "2026-11-05", "started_at": "2026-11-05T16:04:22+08:00"}

    def test_same_scheduled_slot_is_stable_across_runs(self):
        a = delivery_identity(self.report, event_name="schedule", run_id="100")
        b = delivery_identity(self.report, event_name="schedule", run_id="101")
        self.assertEqual(a, b)
        self.assertEqual(a, "schedule:2026-11-05:16")

    def test_manual_runs_remain_distinct(self):
        a = delivery_identity(self.report, event_name="workflow_dispatch", run_id="100")
        b = delivery_identity(self.report, event_name="workflow_dispatch", run_id="101")
        self.assertNotEqual(a, b)

    def test_watchdog_recovery_uses_durable_slot_marker(self):
        a = delivery_identity(self.report, event_name="workflow_dispatch", run_id="100",
                              recovery_slot="recovery:20261105-1600")
        self.assertEqual(a, "recovery:20261105-1600")

    def test_invalid_schedule_hour_fails_closed(self):
        report = {**self.report, "started_at": "2026-11-05T15:05:00+08:00"}
        with self.assertRaises(ValueError):
            delivery_identity(report, event_name="schedule", run_id="100")

if __name__ == "__main__":
    unittest.main()
