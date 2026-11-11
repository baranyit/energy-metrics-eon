"""Re-importing data must replace, never add up (no Home Assistant needed)."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest

_PATH = Path(__file__).parents[1] / "custom_components" / "eon_w1000" / "merge.py"
_spec = importlib.util.spec_from_file_location("eon_w1000_merge", _PATH)
merge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(merge)


def h(hour, day=1):
    return datetime(2026, 1, day, hour, tzinfo=timezone.utc)


class Store:
    """Mimics the recorder: rows are upserted by their start time."""

    def __init__(self):
        self.rows = {}

    def import_(self, hourly):
        existing = {s: (r["state"], r["sum"]) for s, r in self.rows.items()}
        for row in merge.merge_hourly(existing, hourly):
            self.rows[row["start"]] = row

    def total(self):
        return self.rows[max(self.rows)]["sum"]


class MergeTest(unittest.TestCase):
    def test_same_file_twice_does_not_double(self):
        store = Store()
        data = {h(9): 0.5, h(10): 1.012, h(11): 0.7}
        store.import_(data)
        store.import_(data)
        self.assertEqual(store.rows[h(10)]["state"], 1.012)
        self.assertAlmostEqual(store.total(), 2.212)

    def test_overlapping_files(self):
        store = Store()
        store.import_({h(9): 0.5, h(10): 1.012})
        store.import_({h(10): 1.012, h(11): 0.7})  # 10:00 arrives again
        self.assertEqual([r["sum"] for r in store.rows.values()], [0.5, 1.512, 2.212])

    def test_correction_replaces_value(self):
        store = Store()
        store.import_({h(9): 0.5, h(10): 1.0, h(11): 0.7})
        store.import_({h(10): 1.2})
        self.assertEqual(store.rows[h(10)]["state"], 1.2)
        self.assertAlmostEqual(store.total(), 2.4)

    def test_older_period_imported_later(self):
        store = Store()
        store.import_({h(10, day=2): 2.0})
        store.import_({h(10, day=1): 1.0})  # backfill
        self.assertEqual(store.rows[h(10, day=1)]["sum"], 1.0)
        self.assertEqual(store.rows[h(10, day=2)]["sum"], 3.0)
        store.import_({h(10, day=1): 1.0})  # and once more
        self.assertEqual(store.total(), 3.0)

    def test_nothing_new(self):
        self.assertEqual(merge.merge_hourly({h(9): (1.0, 1.0)}, {}), [])


def q(hour, minute, day=1):
    return datetime(2026, 1, day, hour, minute, tzinfo=timezone.utc)


QUARTER = timedelta(minutes=15)


class Pipeline:
    """Interval store + statistics, the way the coordinator chains them."""

    def __init__(self):
        self.days = {}
        self.stats = Store()

    def import_(self, intervals, step=QUARTER):
        touched = merge.merge_intervals(self.days, intervals, step)
        self.stats.import_(merge.hourly_from_intervals(self.days, touched))

    def state(self, hour, day=1):
        return self.stats.rows[h(hour, day)]["state"]


class IntervalMergeTest(unittest.TestCase):
    def full_hour(self, hour, value, day=1):
        return {q(hour, m, day): value for m in (0, 15, 30, 45)}

    def test_same_quarters_twice_do_not_double(self):
        p = Pipeline()
        data = {**self.full_hour(9, 0.25), q(10, 0): 1.012}
        p.import_(data)
        p.import_(data)
        self.assertEqual(p.state(9), 1.0)
        self.assertEqual(p.state(10), 1.012)
        self.assertAlmostEqual(p.stats.total(), 2.012)

    def test_gap_in_later_file_keeps_earlier_quarter(self):
        p = Pipeline()
        p.import_(self.full_hour(10, 0.25))
        gappy = self.full_hour(10, 0.25)
        del gappy[q(10, 30)]  # empty cell in the middle of the next file
        p.import_({**self.full_hour(9, 0.5), **gappy, **self.full_hour(11, 0.5)})
        self.assertEqual(p.state(10), 1.0)
        self.assertAlmostEqual(p.stats.total(), 5.0)

    def test_partial_hour_completed_later(self):
        p = Pipeline()
        p.import_({q(10, 0): 0.1, q(10, 15): 0.2})  # file cut off at 10:30
        self.assertAlmostEqual(p.state(10), 0.3)
        p.import_({q(10, 30): 0.3, q(10, 45): 0.4, **self.full_hour(11, 1.0)})
        self.assertAlmostEqual(p.state(10), 1.0)
        self.assertAlmostEqual(p.stats.total(), 5.0)

    def test_corrected_quarter_replaces(self):
        p = Pipeline()
        p.import_(self.full_hour(10, 0.25))
        p.import_({q(10, 15): 0.5})
        self.assertAlmostEqual(p.state(10), 1.25)

    def test_overlapping_days(self):
        p = Pipeline()
        p.import_({**self.full_hour(23, 1.0, day=1), **self.full_hour(0, 1.0, day=2)})
        p.import_({**self.full_hour(0, 1.0, day=2), **self.full_hour(1, 1.0, day=2)})
        self.assertEqual(p.stats.total(), 12.0)

    def test_hourly_resolution(self):
        p = Pipeline()
        p.import_({h(10): 1.5}, step=timedelta(hours=1))
        p.import_({h(10): 1.5, h(11): 2.0}, step=timedelta(hours=1))
        self.assertEqual(p.stats.total(), 3.5)

    def test_store_is_json_serialisable(self):
        import json

        days = {}
        merge.merge_intervals(days, self.full_hour(10, 0.25), QUARTER)
        self.assertEqual(json.loads(json.dumps(days)), days)
        self.assertEqual(len(days["2026-01-01"]["v"]), 96)

    def test_rejects_odd_step(self):
        with self.assertRaises(ValueError):
            merge.merge_intervals({}, {q(10, 0): 1}, timedelta(minutes=7))


if __name__ == "__main__":
    unittest.main()
