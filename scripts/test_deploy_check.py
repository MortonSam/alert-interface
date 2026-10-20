"""deploy_check: Railway's running commit must be the one just pushed (2026-10-20: two pushes started no Railway deployment).
Run: python3 -m unittest scripts/test_deploy_check.py"""
import unittest

import deploy_check as D

STATUS = {"environments": {"edges": [{"node": {"serviceInstances": {"edges": [
    {"node": {"serviceName": "Postgres", "activeDeployments": [{"meta": {}}]}},
    {"node": {"serviceName": "alert-interface", "activeDeployments": [{"meta": {"commitHash": "e236e6da71124a5cedd5941c99283ad5c092c041"}}]}}]}}}]}}


class DeployCheck(unittest.TestCase):
    def test_reads_the_services_running_commit_and_the_pushed_commits_deployment(self):
        self.assertEqual(D.running_commit(STATUS), "e236e6da71124a5cedd5941c99283ad5c092c041")
        self.assertIsNone(D.running_commit({}))
        deps = [{"status": "BUILDING", "meta": {"commitHash": "55aeb08abc"}}, {"status": "SUCCESS", "meta": {"commitHash": "e236e6da7"}}]
        self.assertEqual(D.latest_for(deps, "55aeb08")["status"], "BUILDING")
        self.assertIsNone(D.latest_for(deps, "f77172a"))

    def test_ok_only_when_the_pushed_commit_runs(self):
        self.assertEqual(D.verdict("e236e6d", "e236e6da71124a5c", None, 0)[0], "ok")
        self.assertEqual(D.verdict("55aeb08", "e236e6da71124a5c", {"status": "BUILDING"}, 120)[0], "wait")

    def test_fails_loudly_when_railway_never_starts_fails_or_runs_another_commit(self):
        state, msg = D.verdict("f77172a", "e236e6da71124a5c", None, D.NO_START_S)          # the 2026-10-20 case
        self.assertEqual(state, "fail")
        self.assertIn("started no deployment of f77172a", msg)
        self.assertIn("still running e236e6da", msg)
        self.assertEqual(D.verdict("55aeb08", "e236e6da", {"status": "FAILED"}, 60)[0], "fail")
        self.assertEqual(D.verdict("55aeb08", "e236e6da", {"status": "DEPLOYING"}, D.WAIT_S)[0], "fail")
        self.assertEqual(D.verdict("55aeb08", None, None, 30)[0], "wait")


class TheGateRunsIt(unittest.TestCase):
    def test_push_window_checks_after_a_push_to_main(self):
        import inspect
        import push_window
        src = inspect.getsource(push_window.main)
        self.assertIn("deploy_check.main([pushed_sha(argv)])", src)
        self.assertIn('"--no-deploy-check" in argv', src)


if __name__ == "__main__":
    unittest.main()
