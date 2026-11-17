"""A fast child's artefact must not be classified as stale.

    python3 -m unittest discover -s tests -v

Regression: started was time.time() taken AFTER Popen. A child that wrote its file
in the same clock tick produced an mtime earlier than started, so verify() called a
fresh artefact stale. The start marker is created before the spawn.
"""

import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-marker-"))

import klieg_core as core


class StartMarker(unittest.TestCase):
    def test_started_precedes_child_write(self):
        d = tempfile.mkdtemp(prefix="klieg-fast-")
        art = os.path.join(d, "0000.png")
        # Child writes immediately, no sleep.
        j = core.launch("fast", ["/bin/sh", "-c", f"echo x > {art}"],
                        guard=[art], expect={"dir": d, "min": 1, "ext": ".png"})
        for _ in range(60):
            if os.path.exists(art):
                break
            time.sleep(0.05)
        st = core.read_status(j["job"])
        self.assertTrue(os.path.isfile(st["marker"]))
        self.assertLessEqual(st["started"], os.path.getmtime(art) + 0.01)
        v = core.verify(j["job"])
        self.assertTrue(v["ok"], v)
        self.assertEqual(len(v["artefacts"]), 1)
        self.assertEqual(len(v["stale"]), 0)

    def test_marker_created_before_status(self):
        j = core.launch("mark", ["/bin/sh", "-c", "true"])
        for _ in range(60):
            if core.poll(j["job"])["state"] != "running":
                break
            time.sleep(0.05)
        st = core.read_status(j["job"])
        self.assertIn("marker", st)
        self.assertTrue(os.path.isfile(st["marker"]))


if __name__ == "__main__":
    unittest.main()
