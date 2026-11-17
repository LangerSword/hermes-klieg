"""Bad frame strings return data, never a traceback.

    python3 -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-frames-"))

import klieg_tools as tools


class FrameValidation(unittest.TestCase):
    def test_valid_specs(self):
        self.assertEqual(tools.parse_frames("0-3")[0], [0, 1, 2, 3])
        self.assertEqual(tools.parse_frames("0,5,9")[0], [0, 5, 9])
        self.assertEqual(tools.parse_frames("0-2,7")[0], [0, 1, 2, 7])
        self.assertEqual(tools.parse_frames([4, 2])[0], [4, 2])

    def test_invalid_specs_return_error(self):
        for bad in ("abc", "1-", "3-1", "1,,2", "1.5", "-1"):
            frames, err = tools.parse_frames(bad)
            self.assertIsNotNone(err, bad)
            self.assertEqual(frames, [])

    def test_render_rejects_bad_frames_without_raising(self):
        out = json.loads(tools.h_render({"frames": "abc", "blend": "/tmp/x.blend",
                                         "outdir": "/tmp/x"}))
        self.assertFalse(out.get("ok", True))
        self.assertIn("error", out)

    def test_plan_reports_bad_frames_as_blocker(self):
        out = json.loads(tools.h_plan({"frames": "abc"}))
        self.assertFalse(out["would_run"])
        self.assertTrue(any("frames" in b for b in out["blockers"]))


if __name__ == "__main__":
    unittest.main()
