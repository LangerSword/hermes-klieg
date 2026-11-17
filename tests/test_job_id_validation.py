"""Job ids are validated and confined to the jobs directory.

    python3 -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-jobid-"))

import klieg_core as core
import klieg_tools as tools


class JobIdValidation(unittest.TestCase):
    def test_valid_ids(self):
        for j in ("render-a1b2c3d4", "x", "A_B-9"):
            self.assertTrue(core.valid_job_id(j), j)

    def test_traversal_ids_rejected(self):
        for j in ("../../etc", "../x", "/etc", "a/b", "", "x" * 65, "a b"):
            self.assertFalse(core.valid_job_id(j), j)

    def test_core_raises_on_traversal(self):
        with self.assertRaises(ValueError):
            core.read_status("../../etc")
        with self.assertRaises(ValueError):
            core.tail("../x")

    def test_tool_returns_error_data(self):
        out = json.loads(tools.h_jobs({"action": "status", "job": "../../etc"}))
        self.assertFalse(out.get("ok", True))
        self.assertIn("invalid job id", out["error"])


if __name__ == "__main__":
    unittest.main()
