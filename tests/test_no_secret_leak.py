"""No secret may reach any child process, on any spawn path.

    python3 -m unittest discover -s tests -v

The README promised a 13-variable allow-list and "never os.environ". Only the detached
render path used core.child_environment(); foreground tools built env from os.environ.
This test plants fake secrets and calls each tool, asserting the child env is clean.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-leak-"))

import klieg_core as core
import klieg_tools as tools


SECRETS = {"FAKE_PROVIDER_API_KEY": "x", "OPENAI_API_KEY": "x"}


class ChildEnvLeak(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="klieg-env-")
        for k, v in SECRETS.items():
            os.environ[k] = v
        self.script = os.path.join(self.dir, "ok.py")
        with open(self.script, "w") as f:
            f.write("print('ok')\n")
        self.blend = os.path.join(self.dir, "a.blend")
        open(self.blend, "w").close()

    def tearDown(self):
        for k in SECRETS:
            os.environ.pop(k, None)

    def _run_and_capture(self, fn):
        """Patch subprocess.run globally; every tool path lands here."""
        seen = []

        def fake_run(argv, **kw):
            seen.append(kw.get("env"))
            return mock.Mock(returncode=0, stdout='KLIIEG_COLOUR {"view_transform": "AgX"}\nKLIIEG_GATE {}\n',
                             stderr="")

        fake_adapter = mock.Mock(detect=lambda: {"found": True},
                                 find_binary=lambda: "/usr/bin/blender")
        with mock.patch("subprocess.run", side_effect=fake_run), \
             mock.patch.object(tools.A, "get", return_value=fake_adapter):
            fn()
        self.assertTrue(seen, "no subprocess was spawned")
        return seen

    def _assert_clean(self, envs):
        allowed = set(core.PASSTHROUGH) | {"PATH"}
        for env in envs:
            self.assertIsInstance(env, dict)
            for secret in SECRETS:
                self.assertNotIn(secret, env)
            extra = set(env) - allowed
            self.assertEqual(extra, set(), f"unexpected env keys: {extra}")

    def test_run_child_environment_is_clean(self):
        seen = self._run_and_capture(lambda: tools.h_run({"script": self.script}))
        self._assert_clean(seen)

    def test_scene_child_environment_is_clean(self):
        seen = self._run_and_capture(lambda: tools.h_scene({"blend": self.blend}))
        self._assert_clean(seen)

    def test_track_child_environment_is_clean(self):
        seen = self._run_and_capture(lambda: tools.h_track({"script": self.script}))
        self._assert_clean(seen)

    def test_gate_child_environment_is_clean(self):
        seen = self._run_and_capture(lambda: tools.h_gate({"script": self.script}))
        self._assert_clean(seen)

    def test_adapter_version_probe_environment_is_clean(self):
        import klieg_adapters as A
        seen = self._run_and_capture(lambda: A.Blender().version("/usr/bin/blender"))
        self._assert_clean(seen)

    def test_colour_batch_probe_environment_is_clean(self):
        import klieg_colour as C
        seen = self._run_and_capture(lambda: C.probe_batch("/usr/bin/blender", self.blend))
        self._assert_clean(seen)

    def test_child_environment_drops_secretish_extras(self):
        env, dropped = core.child_environment({"OPENAI_API_KEY": "x", "KLIEG_OK": "1"})
        self.assertIn("OPENAI_API_KEY", dropped)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertEqual(env["KLIEG_OK"], "1")


if __name__ == "__main__":
    unittest.main()
