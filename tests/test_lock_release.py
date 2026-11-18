"""The GPU lock must be released when the job exits, not on a status poll."""

import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-lock-"))

import klieg_core as core


class LockRelease(unittest.TestCase):
    def test_lock_clears_when_job_exits_without_status_call(self):
        dcc = "watchgpu"
        j = core.launch("watch", ["/bin/sh", "-c", "exit 0"], dcc=dcc, queue=False)
        self.assertIsNotNone(core.gpu_busy(dcc))

        # Deliberately do NOT call core.poll(), list_jobs(), or any status helper.
        deadline = time.time() + 3
        while time.time() < deadline and core.gpu_busy(dcc) is not None:
            time.sleep(0.02)
        self.assertIsNone(core.gpu_busy(dcc), "lock stayed held after process exit")

        second = core.launch("watch2", ["/bin/sh", "-c", "exit 0"], dcc=dcc, queue=False)
        self.assertEqual(second["state"], "running")
        self.assertNotEqual(second["state"], "refused")

    def test_lock_clears_on_failed_job_too(self):
        dcc = "failgpu"
        j = core.launch("fail", ["/bin/sh", "-c", "exit 3"], dcc=dcc, queue=False)
        deadline = time.time() + 3
        while time.time() < deadline and core.gpu_busy(dcc) is not None:
            time.sleep(0.02)
        self.assertIsNone(core.gpu_busy(dcc))


if __name__ == "__main__":
    unittest.main()
