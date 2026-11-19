"""Regression: concurrent status writes must not collide on the tmp file.

The watcher thread and a poll can finalize the same job at once. A shared
status.json.tmp name let one os.replace move the file out from under the other
(FileNotFoundError on CI, green locally). Each writer now uses a pid+tid-unique
tmp so every os.replace is atomic and independent.
"""

import os
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-race-"))

import klieg_core as core


class StatusWriteRace(unittest.TestCase):
    def test_concurrent_writes_do_not_collide(self):
        job = "race-job"
        os.makedirs(core._job_dir(job), exist_ok=True)
        core._write_status(job, job=job, state="running")
        errors = []

        def writer(n):
            try:
                for i in range(60):
                    core._write_status(job, tick=n * 1000 + i)
            except Exception as e:  # noqa: BLE001 - record, assert below
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [], f"concurrent status writes raised: {errors[:3]}")
        st = core.read_status(job)
        self.assertEqual(st["job"], job)
        # no stray tmp files left behind
        leftovers = [n for n in os.listdir(core._job_dir(job)) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [], leftovers)


if __name__ == "__main__":
    unittest.main()