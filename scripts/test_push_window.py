"""The no-push window across its boundaries, a weekend, a DST date and a UTC clock. Run: python3 -m unittest scripts/test_push_window.py"""
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from push_window import in_window

NY = ZoneInfo("America/New_York")


class PushWindow(unittest.TestCase):
    def test_boundaries_on_a_weekday(self):
        self.assertFalse(in_window(datetime(2026, 10, 5, 15, 59, 59, tzinfo=NY)))
        self.assertTrue(in_window(datetime(2026, 10, 5, 16, 0, 0, tzinfo=NY)))
        self.assertTrue(in_window(datetime(2026, 10, 5, 16, 45, 0, tzinfo=NY)))
        self.assertFalse(in_window(datetime(2026, 10, 5, 16, 45, 1, tzinfo=NY)))
        self.assertFalse(in_window(datetime(2026, 10, 5, 19, 20, tzinfo=NY)))

    def test_weekends_are_open(self):
        self.assertFalse(in_window(datetime(2026, 10, 10, 16, 20, tzinfo=NY)))    # Saturday
        self.assertFalse(in_window(datetime(2026, 10, 11, 16, 20, tzinfo=NY)))    # Sunday

    def test_a_utc_clock_is_read_on_the_new_york_wall(self):
        self.assertTrue(in_window(datetime(2026, 10, 5, 20, 20, tzinfo=timezone.utc)))    # 16:20 EDT
        self.assertFalse(in_window(datetime(2026, 10, 5, 21, 20, tzinfo=timezone.utc)))   # 17:20 EDT

    def test_the_window_follows_the_wall_clock_across_dst(self):
        # 2026-11-02 is the first Monday after the fall-back: 16:20 EST is 21:20Z, and 20:20Z (the summer offset) is 15:20 EST
        self.assertTrue(in_window(datetime(2026, 11, 2, 21, 20, tzinfo=timezone.utc)))
        self.assertFalse(in_window(datetime(2026, 11, 2, 20, 20, tzinfo=timezone.utc)))
        self.assertTrue(in_window(datetime(2026, 11, 2, 16, 20, tzinfo=NY)))

    def test_a_naive_time_is_new_york(self):
        self.assertTrue(in_window(datetime(2026, 10, 5, 16, 30)))


if __name__ == "__main__":
    unittest.main()
