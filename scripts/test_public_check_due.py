"""When the scheduled public-pages check runs, and the one alarm it sends. Run: python3 -m unittest scripts/test_public_check_due.py"""
import unittest
from datetime import datetime, timezone

from public_check_due import ALARM_LINES, alarm_text, due

NOW = datetime(2026, 10, 16, 2, 10, tzinfo=timezone.utc)
MAIN = [{"name": "main"}, {"name": "walkthrough-fixes"}]


class Due(unittest.TestCase):
    def test_a_deploy_on_main_runs_it(self):
        for ctx in ("Vercel", "enchanting-cooperation - alert-interface"):
            run, why = due("status", {"context": ctx, "state": "success", "branches": MAIN, "sha": "8476910abc"}, None, NOW)
            self.assertTrue(run, why)
            self.assertIn("8476910", why)

    def test_a_pending_deploy_a_preview_or_another_status_does_not(self):
        self.assertFalse(due("status", {"context": "Vercel", "state": "pending", "branches": MAIN}, None, NOW)[0])
        self.assertFalse(due("status", {"context": "Vercel", "state": "success", "branches": [{"name": "design-pass"}]}, None, NOW)[0])
        self.assertFalse(due("status", {"context": "ci/other", "state": "success", "branches": MAIN}, None, NOW)[0])

    def test_the_schedule_runs_once_after_a_finished_refresh(self):
        h = {"refresh_in_progress": False, "refresh_started_at": None, "last_refreshed_at": "2026-10-16T01:20:00+00:00"}
        self.assertTrue(due("schedule", {}, h, NOW)[0])                                   # 50 minutes ago
        h["last_refreshed_at"] = "2026-10-16T01:05:00+00:00"
        self.assertFalse(due("schedule", {}, h, NOW)[0])                                  # 65 minutes ago: the previous hour ran it
        h["last_refreshed_at"] = "2026-10-16T02:30:00+00:00"
        self.assertFalse(due("schedule", {}, h, NOW)[0])                                  # a clock ahead of ours is not "just finished"

    def test_the_schedule_waits_for_a_running_refresh_and_an_unreadable_health(self):
        h = {"refresh_in_progress": False, "refresh_started_at": "2026-10-16T01:00:00+00:00", "last_refreshed_at": "2026-10-16T01:50:00Z"}
        self.assertFalse(due("schedule", {}, h, NOW)[0])
        self.assertFalse(due("schedule", {}, None, NOW)[0])

    def test_by_hand_always_runs(self):
        self.assertTrue(due("workflow_dispatch", {}, None, NOW)[0])
        self.assertFalse(due("push", {}, None, NOW)[0])


class Alarm(unittest.TestCase):
    def test_one_alarm_names_the_failing_routes(self):
        out = "ok   /\nFAIL /tickers/VMRK\n  developer message: \"being regenerated now\"\nok   /discover\n18 route(s), 1 failing; patterns: token count"
        title, body = alarm_text(out, "https://github.com/run/1")
        self.assertEqual(title, "Public pages check: 1 route(s) failing")
        self.assertIn("FAIL /tickers/VMRK", body)
        self.assertIn("being regenerated", body)
        self.assertIn("18 route(s), 1 failing", body)
        self.assertTrue(body.endswith("https://github.com/run/1"))

    def test_a_check_that_did_not_finish_still_alarms_and_a_long_list_is_cut(self):
        self.assertEqual(alarm_text("", "u")[0], "Public pages check did not finish")
        out = "\n".join(f"FAIL /p{i}" for i in range(30))
        self.assertIn(f"... {30 - ALARM_LINES} more", alarm_text(out, "u")[1])


if __name__ == "__main__":
    unittest.main()
