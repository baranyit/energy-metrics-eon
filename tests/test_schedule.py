"""Polling pause after a daily export e-mail (no Home Assistant needed)."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest

_PATH = Path(__file__).parents[1] / "custom_components" / "energy_metrics_eon" / "schedule.py"
_spec = importlib.util.spec_from_file_location("energy_metrics_eon_schedule", _PATH)
schedule = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(schedule)

HOUR = timedelta(hours=1)
EMAIL = datetime(2026, 11, 11, 6, 5, tzinfo=timezone.utc)


class ScheduleTest(unittest.TestCase):
    def test_polls_when_nothing_processed_yet(self):
        self.assertTrue(schedule.should_poll(EMAIL, None, False))

    def test_quiet_for_22_hours_after_email(self):
        for after in (timedelta(0), HOUR, timedelta(hours=21, minutes=59)):
            self.assertFalse(schedule.should_poll(EMAIL + after, EMAIL, False), after)
        for after in (timedelta(hours=22), timedelta(hours=30), timedelta(days=3)):
            self.assertTrue(schedule.should_poll(EMAIL + after, EMAIL, False), after)

    def test_retry_ignores_quiet_period(self):
        self.assertTrue(schedule.should_poll(EMAIL + HOUR, EMAIL, True))

    def test_next_check_during_quiet_period(self):
        now = EMAIL + timedelta(minutes=10)  # update right after the e-mail
        nxt = schedule.next_check(now, EMAIL, False, HOUR)
        self.assertGreaterEqual(nxt, EMAIL + schedule.QUIET_PERIOD)
        self.assertLess(nxt, EMAIL + schedule.QUIET_PERIOD + HOUR)
        self.assertEqual((nxt - now) % HOUR, timedelta(0))  # on the update grid

    def test_next_check_after_quiet_period(self):
        now = EMAIL + timedelta(hours=23)
        self.assertEqual(schedule.next_check(now, EMAIL, False, HOUR), now + HOUR)
        self.assertEqual(schedule.next_check(now, None, False, HOUR), now + HOUR)
        self.assertEqual(schedule.next_check(EMAIL, EMAIL, True, HOUR), EMAIL + HOUR)


if __name__ == "__main__":
    unittest.main()
