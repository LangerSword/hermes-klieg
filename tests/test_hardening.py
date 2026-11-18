"""Colour/session hardening and the per-action approval policy.

Regressions: colour write crashed on a relative blend path (dirname "") and
could write into ~/.ssh; the batch probe used a fixed /tmp script shared by
every profile; probe_session's strip("'") broke on apostrophes; dead sessions
accumulated forever; and the approval gate treated whole tools as one verb.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-hard-"))

import klieg_core as core
import klieg_colour as C
import klieg_hooks as H
import klieg_tools as tools


class ApprovalPolicy(unittest.TestCase):
    def test_readonly_session_actions_do_not_prompt(self):
        for action in ("status", "list", "colour"):
            self.assertIsNone(H.pre_tool_call("klieg_session", {"action": action}), action)

    def test_mutating_session_actions_prompt(self):
        for action in ("start", "eval", "stop"):
            r = H.pre_tool_call("klieg_session", {"action": action, "code": "import os"})
            assert r is not None, action
            self.assertEqual(r["action"], "approve")
            self.assertEqual(r["rule_key"], "klieg:klieg_session")

    def test_eval_approval_shows_the_code(self):
        r = H.pre_tool_call("klieg_session", {"action": "eval", "code": "bpy.ops.mesh.primitive_cube_add()"})
        assert r is not None
        self.assertIn("primitive_cube_add", r["message"])

    def test_colour_write_prompts_but_reads_do_not(self):
        for action in ("probe", "compare", "tags"):
            self.assertIsNone(H.pre_tool_call("klieg_colour", {"action": action}), action)
        r = H.pre_tool_call("klieg_colour", {"action": "write", "blend": "s.blend"})
        assert r is not None
        self.assertEqual(r["rule_key"], "klieg:klieg_colour")

    def test_jobs_policy_unchanged(self):
        for action in ("list", "status", "log", "verify"):
            self.assertIsNone(H.pre_tool_call("klieg_jobs", {"action": action}), action)
        for action in ("kill", "queue"):
            self.assertIsNotNone(H.pre_tool_call("klieg_jobs", {"action": action}), action)

    def test_executing_verbs_still_prompt(self):
        for tool in sorted(H.EXECUTING):
            self.assertIsNotNone(H.pre_tool_call(tool, {}), tool)


class ColourWrite(unittest.TestCase):
    def setUp(self):
        # Outside every forbidden write root: TMPDIR may point inside ~/.hermes.
        base = os.path.join(os.path.expanduser("~"), ".cache", "klieg-tests")
        os.makedirs(base, exist_ok=True)
        self.tmp = tempfile.mkdtemp(prefix="klieg-cw-", dir=base)
        self.blend = os.path.join(self.tmp, "s.blend")
        with open(self.blend, "w") as f:
            f.write("x")

    def _probe(self):
        return {"view_transform": "AgX", "exposure": 0.0}

    def test_relative_blend_write_does_not_crash(self):
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            with mock.patch.object(tools.A, "get") as g, \
                 mock.patch.object(tools.colour_mod, "probe_batch", return_value=self._probe()):
                ad = mock.Mock()
                ad.detect.return_value = {"found": True}
                ad.find_binary.return_value = "/fake/blender"
                g.return_value = ad
                res = json.loads(tools.h_colour({"action": "write", "blend": "s.blend"}))
            self.assertIn("written", res, res)
            self.assertTrue(os.path.exists(res["written"]))
        finally:
            os.chdir(cwd)

    def test_write_refuses_credential_dirs(self):
        with mock.patch.object(tools.A, "get") as g, \
             mock.patch.object(tools.colour_mod, "probe_batch", return_value=self._probe()):
            ad = mock.Mock()
            ad.detect.return_value = {"found": True}
            ad.find_binary.return_value = "/fake/blender"
            g.return_value = ad
            res = json.loads(tools.h_colour({"action": "write", "blend": self.blend,
                                             "into": "~/.ssh"}))
        self.assertIn("refusing", res["error"])

    def test_batch_probe_script_is_confined_and_cleaned(self):
        seen = {}

        def fake_run(argv, **kw):
            seen["argv"] = argv
            return mock.Mock(stdout='KLIIEG_COLOUR {"view_transform": "AgX"}\n', stderr="")

        with mock.patch.object(core, "run_child", side_effect=fake_run):
            m = C.probe_batch("/fake/blender", self.blend)
        self.assertEqual(m["view_transform"], "AgX")
        script = seen["argv"][-1]
        self.assertTrue(script.startswith(core.data_dir()), script)
        self.assertFalse(os.path.exists(script), "probe script must be cleaned up")

    def test_session_probe_survives_apostrophes(self):
        manifest = {"look": "it's a look", "view_transform": "AgX"}

        # FakeBridge.eval is the bridge's socket RPC method (sends code to the
        # approval-gated Blender host), not Python eval(); the parser under test
        # is ast.literal_eval, which only accepts literals.
        class FakeBridge:
            def eval(self, code="", expr="None", timeout=None):
                return {"ok": True, "result": repr(json.dumps(manifest, sort_keys=True))}

        self.assertEqual(C.probe_session(FakeBridge()), manifest)


class SessionPrune(unittest.TestCase):
    def test_list_prunes_dead_sessions(self):
        sessions_path = os.path.join(core.data_dir(), "sessions.json")
        with open(sessions_path, "w") as f:
            json.dump({"/tmp/dead.sock": {"job": "gone-job", "dcc": "blender"},
                       "/tmp/live.sock": {"job": "live-job", "dcc": "blender"}}, f)

        def fake_poll(job):
            return {"state": "done" if job == "gone-job" else "running"}

        with mock.patch.object(core, "poll", side_effect=fake_poll):
            res = json.loads(tools.h_session({"action": "list"}))
        socks = [s["socket"] for s in res["sessions"]]
        self.assertEqual(socks, ["/tmp/live.sock"])
        with open(sessions_path) as f:
            self.assertNotIn("/tmp/dead.sock", json.load(f))


if __name__ == "__main__":
    unittest.main()