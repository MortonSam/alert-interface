"""The no-push window across its boundaries, a weekend, a DST date and a UTC clock, and the gate that refuses to push on any failed
step. Run: python3 -m unittest scripts/test_push_window.py"""
import unittest
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import push_window
from push_window import REBUILD_TEST_DB, REBUILD_VALIDATE_DB, STEPS, TEST_DB, VALIDATE_DB, VALIDATE_FIXTURE, foreground_steps, push_command, gate, in_window, lane_for, steps_for

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


class Gate(unittest.TestCase):
    def test_every_step_must_exit_zero(self):
        self.assertEqual(gate([("backend tests", 0), ("frontend tests", 0), ("frontend build", 0)])[0], True)
        ok, why = gate([("backend tests", 0), ("frontend tests", 1)])
        self.assertFalse(ok); self.assertIn("frontend tests (exit 1)", why)
        self.assertFalse(gate([("backend tests", 2)])[0])

    def test_the_steps_are_the_two_suites_and_the_build(self):
        self.assertEqual([name for name, _, _ in STEPS], ["backend tests", "validate smoke", "host tests", "frontend tests", "frontend build"])
        for _, cmd, _ in STEPS:
            self.assertNotIn("|", " ".join(cmd))                  # exit codes are read directly, never through a pipe


class LaneTests(unittest.TestCase):
    def test_a_push_of_frontend_files_only_takes_the_frontend_lane(self):
        self.assertEqual(lane_for(["frontend/src/app/page.tsx", "frontend/src/lib/x.ts"], []), "frontend")
        self.assertEqual(lane_for(["frontend/src/app/page.tsx", "backend/app/main.py"], []), "full")
        self.assertEqual(lane_for(["CLAUDE.md"], []), "full")
        self.assertEqual(lane_for([], []), "full")                                   # nothing to push, or an unreadable diff: the full gate
        self.assertEqual(lane_for(["frontend/src/app/page.tsx"], ["--full"]), "full")
        self.assertEqual(lane_for(["backend/app/main.py"], ["--frontend-only"]), "frontend")

    def test_the_frontend_lane_keeps_both_frontend_steps_and_the_full_lane_all_three(self):
        self.assertEqual([name for name, _, _ in steps_for("frontend")], ["frontend tests", "frontend build"])
        self.assertEqual(steps_for("full"), STEPS)

    def test_a_ref_pushes_that_commit_to_main_and_nothing_else(self):
        self.assertEqual(push_command(["--ref=d03b2b7"]), ["git", "push", "origin", "d03b2b7:main"])
        for bad in ("--ref=HEAD~4", "--ref=main", "--ref=abc", "--ref=d03b2b7;rm"):
            with self.assertRaises(SystemExit):
                push_command([bad])

    def test_a_preview_branch_pushes_head_to_that_branch_and_never_to_main(self):
        self.assertEqual(push_command([]), ["git", "push", "origin", "main"])
        self.assertEqual(push_command(["--branch=brand"]), ["git", "push", "origin", "HEAD:refs/heads/brand"])
        with self.assertRaises(SystemExit):
            push_command(["--branch=main"])

    def test_the_full_lane_runs_the_host_tests_beside_the_backend_suite(self):
        self.assertEqual([n for n, _, _ in foreground_steps("full")], ["validate smoke", "host tests", "frontend tests", "frontend build"])
        self.assertEqual([n for n, _, _ in foreground_steps("frontend")], ["frontend tests", "frontend build"])
        host = next(c for n, c, _ in STEPS if n == "host tests")
        self.assertEqual(host[1:], ["-m", "unittest", "discover", "-s", "scripts", "-p", "test_*.py"])   # picks up test_courier_wrapper.py

    def test_the_backend_suite_runs_on_the_test_database_in_parallel(self):
        cmd = next(c for n, c, _ in STEPS if n == "backend tests")
        self.assertIn(f"DATABASE_URL=postgresql+asyncpg://alert:alert@db:5432/{TEST_DB}", cmd)
        self.assertIn(f"DATABASE_URL_SYNC=postgresql://alert:alert@db:5432/{TEST_DB}", cmd)
        self.assertEqual(cmd[-4:], ["-n", "auto", "--dist", "loadgroup"])
        self.assertEqual(TEST_DB, "alertdb_test")
        self.assertIn(f"pg_dump -U alert alertdb | psql -q -U alert {TEST_DB}", REBUILD_TEST_DB[-1])
        self.assertIn("set -o pipefail", REBUILD_TEST_DB[-1])

    def test_every_validate_check_runs_read_only_on_its_own_database_from_the_fixture(self):
        cmd = next(c for n, c, _ in STEPS if n == "validate smoke")
        self.assertEqual(cmd[-3:], ["app.scripts.validate_smoke", "--url", f"postgresql+asyncpg://alert:alert@db:5432/{VALIDATE_DB}"])
        self.assertNotIn(VALIDATE_DB, (TEST_DB, "alertdb"))
        self.assertIn(f"pg_dump -U alert --schema-only {TEST_DB} | psql -q -v ON_ERROR_STOP=1 -U alert {VALIDATE_DB}", REBUILD_VALIDATE_DB[-1])
        self.assertIn(f"< {VALIDATE_FIXTURE}", REBUILD_VALIDATE_DB[-1])
        self.assertIn("set -o pipefail", REBUILD_VALIDATE_DB[-1])
        self.assertTrue((Path(__file__).resolve().parents[1] / VALIDATE_FIXTURE).is_file())

    def test_the_clock_used_for_timings_is_the_monotonic_one(self):
        """`time` in the module is datetime.time (the window bounds); timings read push_window.clock.monotonic."""
        self.assertTrue(callable(push_window.clock.monotonic))
        self.assertIn("clock.monotonic()", open(push_window.__file__).read())


class NightlyTests(unittest.TestCase):
    def test_a_running_nightly_blocks_and_says_when_to_retry(self):
        from push_window import nightly_block
        now = datetime(2026, 10, 9, 7, 30, tzinfo=timezone.utc)              # 03:30 New York
        why = nightly_block({"refresh_started_at": "2026-10-09T06:30:10+00:00", "refresh_in_progress": False}, now)
        self.assertIn("running since 02:30 New York (59 min)", why)          # /health's 45-minute rule says not in progress; the marker says otherwise
        self.assertIn("by 08:30 at the latest", why)
        self.assertIsNone(nightly_block({"refresh_started_at": None, "refresh_in_progress": False}, now))
        self.assertIsNone(nightly_block({"refresh_started_at": "2026-10-08T06:30:10+00:00"}, now))            # a day-old marker is dead
        self.assertIn("unreadable", nightly_block(None, now))
        self.assertIn("in progress", nightly_block({"refresh_in_progress": True}, now))                     # an older /health without the field

    def test_no_push_in_the_quarter_hour_before_the_nightly_starts(self):
        from push_window import nightly_block
        self.assertIn("starts at 02:30", nightly_block({}, datetime(2026, 10, 9, 2, 20, tzinfo=NY)))
        self.assertIsNone(nightly_block({}, datetime(2026, 10, 9, 2, 10, tzinfo=NY)))
        self.assertIsNone(nightly_block({}, datetime(2026, 10, 8, 23, 10, tzinfo=NY)))

    def test_a_no_push_run_goes_on_during_a_refresh_and_a_push_waits(self):
        from push_window import nightly_stops
        why = "no push: the production nightly has been running since 14:20 New York (30 min)"
        self.assertFalse(nightly_stops(why, ["--no-push"]))
        self.assertFalse(nightly_stops(why, ["--no-push", "--frontend-only"]))
        self.assertTrue(nightly_stops(why, []))
        self.assertTrue(nightly_stops(why, ["--ref=abc123"]))
        self.assertTrue(nightly_stops(why, ["--branch=ticker-redesign"]))
        self.assertFalse(nightly_stops(None, []))

    def test_main_runs_every_step_under_a_refresh_with_no_push_and_never_pushes(self):
        from unittest import mock
        ran = []
        why = "no push: the production nightly has been running since 14:20 New York (30 min)"
        patches = [mock.patch.object(push_window, "in_window", return_value=False),
                   mock.patch.object(push_window, "nightly_check", return_value=why),
                   mock.patch.object(push_window, "changed_files", return_value=["frontend/src/x.ts"]),
                   mock.patch.object(push_window, "_stop_dev_server", return_value=False),
                   mock.patch.object(push_window, "_run", side_effect=lambda cmd, cwd: ran.append(cmd) or 0)]
        for p in patches:
            p.start()
        try:
            self.assertEqual(push_window.main(["--no-push"]), 0)
            self.assertEqual(len(ran), len(foreground_steps("frontend")))
            self.assertFalse(any(c[:2] == ["git", "push"] for c in ran))
            ran.clear()
            self.assertEqual(push_window.main([]), 1)              # a push waits, before any step
            self.assertEqual(ran, [])
            self.assertEqual(push_window.main(["--check-only", "--no-push"]), 1)
        finally:
            for p in patches:
                p.stop()
