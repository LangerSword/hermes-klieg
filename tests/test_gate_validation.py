"""klieg_gate reports a missing script with the resolved path."""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-gate-"))

import klieg_tools as tools


class GateValidation(unittest.TestCase):
    def test_missing_script_error_has_resolved_path(self):
        out = json.loads(tools.h_gate({"script": "no/such/measure.py"}))
        self.assertFalse(out.get("ok", True))
        self.assertIn("script not found", out["error"])
        self.assertIn(os.path.abspath("no/such/measure.py"), out["error"])

    def test_empty_script_is_reported(self):
        out = json.loads(tools.h_gate({}))
        self.assertFalse(out.get("ok", True))
        self.assertIn("script not found", out["error"])


if __name__ == "__main__":
    unittest.main()
