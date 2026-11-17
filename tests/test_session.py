"""Session server path and job state on host exit.

    python3 -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-session-"))

import klieg_core as core
import klieg_tools as tools


class SessionLifecycle(unittest.TestCase):
    def test_server_script_resolves_to_existing_file(self):
        """The path must be relative to the plugin file, one level up to blender/."""
        server = os.path.join(os.path.dirname(ROOT), "blender", "klieg_headless_server.py")
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "blender", "klieg_headless_server.py")))

    def test_start_uses_the_plugin_root_server_path(self):
        """The argv passed to Blender contains the real server script."""
        seen = {}
        fake_launch = lambda name, argv, **kw: (seen.update(argv=argv), {"job": "live-x", "state": "running"})[1]

        with mock.patch.object(core, "launch", side_effect=fake_launch), \
             mock.patch.object(tools.A, "get", return_value=mock.Mock(
                 detect=lambda: {"found": True}, find_binary=lambda: "/usr/bin/blender")):
            out = json.loads(tools.h_session({"action": "start", "wait": 0}))
        self.assertIn("--python", seen["argv"])
        server_arg = seen["argv"][seen["argv"].index("--python") + 1]
        self.assertTrue(os.path.isfile(server_arg), server_arg)
        self.assertTrue(server_arg.endswith("klieg_headless_server.py"))

    def test_status_reports_job_state_when_host_is_gone(self):
        """A dead Blender cannot leave the session reported as running."""
        sock = os.path.join(tempfile.mkdtemp(prefix="klieg-sess-"), "dead.sock")
        sessions_path = os.path.join(core.data_dir(), "sessions.json")
        with open(sessions_path, "w") as f:
            json.dump({sock: {"job": "gone-job", "dcc": "blender"}}, f)

        with mock.patch.object(tools.bridge_mod.Bridge, "info",
                               side_effect=tools.bridge_mod.BridgeUnavailable("dead")), \
             mock.patch.object(core, "poll", return_value={"state": "failed",
                                                           "note": "host exited"}) as polled:
            out = json.loads(tools.h_session({"action": "status", "socket": sock}))
        self.assertEqual(out["error"], "host not reachable")
        self.assertEqual(out["job"], "gone-job")
        polled.assert_called_once_with("gone-job")
        self.assertEqual(out["job_state"], "failed")


if __name__ == "__main__":
    unittest.main()
