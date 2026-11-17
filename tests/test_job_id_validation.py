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

    def test_non_string_job_ids_rejected(self):
        for j in (123, None, ["x"], {"a": 1}):
            self.assertFalse(core.valid_job_id(j), repr(j))
        out = json.loads(tools.h_jobs({"action": "status", "job": 123}))
        self.assertFalse(out.get("ok", True))
        self.assertIn("invalid job id", out["error"])

    def test_legacy_job_dirs_do_not_break_listing(self):
        junk = os.path.join(core.jobs_dir(), "legacy id with spaces")
        os.makedirs(junk, exist_ok=True)
        with open(os.path.join(junk, "status.json"), "w") as f:
            f.write('{"state":"done"}')
        rows = core.list_jobs(50)
        self.assertIsInstance(rows, list)
        self.assertFalse(any(r.get("job") == "legacy id with spaces" for r in rows))

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
