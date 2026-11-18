"""klieg_session status picks the right message for 0, 1 and many sessions."""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-sessions-"))

import klieg_core as core
import klieg_tools as tools


class SessionMessages(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(core.data_dir(), "sessions.json")

    def test_zero_sessions(self):
        with open(self.path, "w") as f:
            json.dump({}, f)
        out = json.loads(tools.h_session({"action": "status"}))
        self.assertIn("no live sessions", out["error"])
        self.assertEqual(out["sessions"], [])

    def test_one_session_is_selected(self):
        sock = "/tmp/one.sock"
        with open(self.path, "w") as f:
            json.dump({sock: {"job": "j1", "dcc": "blender"}}, f)
        with mock.patch.object(tools.bridge_mod.Bridge, "info",
                               return_value={"ok": True, "result": "{}"}):
            out = json.loads(tools.h_session({"action": "status"}))
        self.assertEqual(out["socket"], sock)
        self.assertNotIn("error", out)

    def test_many_sessions_require_choice(self):
        with open(self.path, "w") as f:
            json.dump({"/tmp/a.sock": {"job": "a"}, "/tmp/b.sock": {"job": "b"}}, f)
        out = json.loads(tools.h_session({"action": "status"}))
        self.assertIn("more than one", out["error"])
        self.assertEqual(len(out["sockets"]), 2)


if __name__ == "__main__":
    unittest.main()
