"""Bad input must come back as data, never as a traceback.

Regression class: handlers indexed args["..."] directly (KeyError), coerced with
int()/float() (ValueError), let subprocess.TimeoutExpired escape, and raised
KeyError for unknown DCCs. A model that mistypes an argument deserves a readable
error it can correct, not a stack trace it will retry blindly.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-valid-"))

import klieg_core as core
import klieg_tools as tools


def call(handler, args):
    """Every handler must return parseable JSON with an 'error', never raise."""
    out = handler(args)
    obj = json.loads(out)
    assert isinstance(obj, dict), obj
    return obj


class StructuredErrors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="klieg-v-")
        self.blend = os.path.join(self.tmp, "s.blend")
        with open(self.blend, "w") as f:
            f.write("x")
        self.script = os.path.join(self.tmp, "s.py")
        with open(self.script, "w") as f:
            f.write("print(1)\n")

    def test_unknown_dcc_is_data_in_every_handler(self):
        cases = [
            (tools.h_render, {"dcc": "maya", "blend": self.blend, "frames": "0", "outdir": self.tmp}),
            (tools.h_run, {"dcc": "maya", "script": self.script}),
            (tools.h_track, {"dcc": "maya", "script": self.script}),
            (tools.h_gate, {"dcc": "maya", "script": self.script}),
            (tools.h_scene, {"dcc": "maya"}),
            (tools.h_colour, {"dcc": "maya", "action": "probe", "blend": self.blend}),
            (tools.h_session, {"dcc": "maya", "action": "start"}),
        ]
        for handler, args in cases:
            with self.subTest(handler=handler.__name__):
                obj = call(handler, args)
                self.assertIn("error", obj)
                self.assertIn("maya", obj["error"])

    def test_missing_required_args_are_data(self):
        cases = [
            (tools.h_render, {"blend": self.blend, "outdir": self.tmp}),          # no frames
            (tools.h_render, {"frames": "0", "outdir": self.tmp}),                # no blend
            (tools.h_render, {"frames": "0", "blend": self.blend}),               # no outdir
            (tools.h_track, {}),                                                  # no script
            (tools.h_publish, {"out": os.path.join(self.tmp, "x.mp4")}),          # no frames_dir
            (tools.h_publish, {"frames_dir": self.tmp}),                          # no out
        ]
        for handler, args in cases:
            with self.subTest(handler=handler.__name__, args=args):
                self.assertIn("error", call(handler, args))

    def test_missing_files_are_data(self):
        cases = [
            (tools.h_render, {"blend": "/nope.blend", "frames": "0", "outdir": self.tmp}),
            (tools.h_track, {"script": "/nope.py"}),
            (tools.h_scene, {"blend": "/nope.blend"}),
            (tools.h_session, {"action": "start", "blend": "/nope.blend"}),
        ]
        for handler, args in cases:
            with self.subTest(handler=handler.__name__):
                self.assertIn("error", call(handler, args))

    def test_malformed_numbers_are_data(self):
        base = {"blend": self.blend, "frames": "0", "outdir": self.tmp}
        for bad in ({"samples": "abc"}, {"pct": 0}, {"pct": 101}, {"samples": -3}):
            with self.subTest(bad=bad):
                self.assertIn("error", call(tools.h_render, {**base, **bad}))
        for bad in ({"fps": 0}, {"fps": "x"}, {"crf": 99}, {"crf": "y"}):
            with self.subTest(bad=bad):
                self.assertIn("error", call(tools.h_publish,
                                            {"frames_dir": self.tmp,
                                             "out": os.path.join(self.tmp, "x.mp4"), **bad}))
        self.assertIn("error", call(tools.h_jobs, {"action": "list", "limit": "many"}))
        self.assertIn("error", call(tools.h_run, {"script": self.script, "timeout": "soon"}))

    def test_bad_input_wins_over_missing_host(self):
        # On a machine without the DCC, a frames error must still be a frames
        # error, not "blender not found" masking the real problem.
        with mock.patch.object(tools.A, "get") as g:
            ad = mock.Mock()
            ad.detect.return_value = {"found": False}
            g.return_value = ad
            obj = call(tools.h_render, {"blend": self.blend, "frames": "zero", "outdir": self.tmp})
        self.assertIn("invalid frame spec", obj["error"])

    def test_timeout_is_data_with_a_hint(self):
        # Stub the adapter to found=True so the timeout path is reached even on
        # a host without Blender (CI); otherwise detect() short-circuits first.
        with mock.patch.object(tools.A, "get") as g, \
             mock.patch.object(tools.core, "run_child",
                               side_effect=subprocess.TimeoutExpired("blender", 1)):
            ad = mock.Mock()
            ad.detect.return_value = {"found": True}
            ad.run_argv.return_value = ["blender", "-b", "-P", "x.py"]
            g.return_value = ad
            obj = call(tools.h_run, {"script": self.script, "timeout": 1})
        self.assertIn("timed out", obj.get("error") or "")
        self.assertIn("bg=true", obj.get("hint") or "")

    def test_frame_spec_cannot_allocate_a_billion_ints(self):
        frames, err = tools.parse_frames("0-999999999")
        self.assertEqual(frames, [])
        self.assertIn("exceeds", err)
        frames, err = tools.parse_frames([str(i) for i in range(tools.MAX_FRAMES + 1)])
        self.assertEqual(frames, [])
        self.assertIn("exceeds", err)

    def test_unsupported_render_adapter_is_data(self):
        # Houdini/Nuke declare run_argv but not render_argv.
        with mock.patch.object(tools.A, "get") as g:
            ad = mock.Mock()
            ad.detect.return_value = {"found": True}
            ad.render_argv.side_effect = NotImplementedError
            g.return_value = ad
            obj = call(tools.h_render, {"dcc": "houdini", "blend": self.blend,
                                        "frames": "0", "outdir": self.tmp})
        self.assertIn("not supported", obj["error"])


class JobNameSanitization(unittest.TestCase):
    def test_model_chosen_name_with_spaces_is_sanitized_not_raised(self):
        j = core.launch("my render/../take 1", ["/bin/sh", "-c", "true"])
        try:
            self.assertTrue(core.valid_job_id(j["job"]), j)
            self.assertEqual(j["state"], "running")
        finally:
            deadline = __import__("time").time() + 5
            st = core.poll(j["job"])
            while st.get("state") == "running" and __import__("time").time() < deadline:
                st = core.poll(j["job"])
            self.assertIn(st.get("state"), ("done", "failed", "killed"))


class TasteVerdict(unittest.TestCase):
    def test_record_requires_explicit_accepted(self):
        try:
            import numpy  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError:
            self.skipTest("numpy/Pillow not installed")
        tmp = tempfile.mkdtemp(prefix="klieg-tv-")
        p = os.path.join(tmp, "f.png")
        Image.new("RGB", (16, 16), (1, 2, 3)).save(p)
        obj = call(tools.h_taste, {"action": "record", "frame": p})
        self.assertIn("explicit", obj["error"])
        obj = call(tools.h_taste, {"action": "record", "frame": p, "accepted": True})
        self.assertTrue(obj.get("recorded"), obj)


if __name__ == "__main__":
    unittest.main()