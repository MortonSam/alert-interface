"""The real courier wrapper (backend/ops/courier/run_courier.sh) under the Mac's /bin/bash (3.2, the shell launchd gives it), with
no simulated clock: the 2026-10-08 wrapper died at its gate line on every fire ("GATE_NOW[@]: unbound variable") because bash 3.2
under set -u treats an empty array as unbound, and no test had run it without COURIER_NOW.
Run: python3 -m unittest discover -s scripts -p 'test_*.py'"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "backend" / "ops" / "courier" / "run_courier.sh"
BASH = "/bin/bash"


def _home() -> Path:
    home = Path(tempfile.mkdtemp(prefix="courier_home_"))
    (home / "projects").mkdir()
    (home / "projects" / "alert-interface").symlink_to(ROOT)
    (home / ".alert-interface").mkdir()
    return home


@unittest.skipUnless(Path(BASH).exists(), "no /bin/bash")
class CourierWrapper(unittest.TestCase):
    def test_with_no_clock_the_gate_line_runs_and_nothing_is_unbound(self):
        home = _home()
        shim_dir = home / "bin"
        shim_dir.mkdir()
        calls = home / "calls.txt"
        shim = shim_dir / "python3"
        shim.write_text(f'#!/bin/bash\necho "$@" >> "{calls}"\nexit 3\n')      # the gate says "not now": the wrapper exits 0
        shim.chmod(0o755)
        env = {"HOME": str(home), "PATH": f"{shim_dir}:/usr/bin:/bin"}            # no COURIER_NOW, as launchd runs it
        try:
            r = subprocess.run([BASH, str(WRAPPER)], env=env, capture_output=True, text=True, timeout=60)
            self.assertNotIn("unbound variable", r.stderr)
            self.assertEqual(r.returncode, 0, r.stderr)
            argv = calls.read_text().split()
            self.assertEqual(argv[:4], ["-m", "app.scripts.courier_gate", "check", "--state"])
            self.assertNotIn("--now", argv)
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_inside_the_window_the_real_gate_starts_a_dry_run(self):
        home = _home()
        env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "COURIER_NOW": "2026-10-12T16:10:00-04:00", "COURIER_DRY_RUN": "1"}
        try:
            r = subprocess.run([BASH, str(WRAPPER)], env=env, capture_output=True, text=True, timeout=120)
            self.assertNotIn("unbound variable", r.stderr)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("DRY RUN: would start the courier now", (home / ".alert-interface" / "courier.log").read_text())
        finally:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
