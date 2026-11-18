"""Built-in gates: measurements with known answers on synthetic sequences.

flash: alternating black/white at 12 fps is 6 flashes/s and must fail the
3/s guideline; a steady sequence passes. loop: identical endpoints close.
stats: constant exposure has zero temporal std. safe_band: detail parked in
the top margin shows up there. All without Blender, through the tool handler.
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-gates-"))

try:
    import numpy as np
    from PIL import Image
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False

import klieg_hooks as H
import klieg_tools as tools


def write_frames(directory, arrays):
    os.makedirs(directory, exist_ok=True)
    for i, arr in enumerate(arrays):
        Image.fromarray(arr.astype(np.uint8)).save(os.path.join(directory, f"{i:04d}.png"))
    return directory


@unittest.skipUnless(HAVE_DEPS, "numpy/Pillow not installed")
class BuiltInGates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="klieg-gt-")

    def _gate(self, name, directory, fps=30, params=None):
        out = json.loads(tools.h_gate({"gate": name, "frames_dir": directory,
                                       "fps": fps, "params": params or {}}))
        self.assertNotIn("error", out, out)
        return out

    def test_flash_alternating_black_white_fails_guideline(self):
        black = np.zeros((48, 64, 3))
        white = np.full((48, 64, 3), 255.0)
        seq = [black if i % 2 == 0 else white for i in range(24)]
        d = write_frames(os.path.join(self.tmp, "flash"), seq)
        out = self._gate("flash", d, fps=12)
        self.assertEqual(out["transitions"], 23)
        self.assertGreater(out["max_flashes_per_second"], 3.0)
        self.assertFalse(out["passes_guideline"])

    def test_flash_steady_sequence_passes(self):
        grey = np.full((48, 64, 3), 128.0)
        d = write_frames(os.path.join(self.tmp, "steady"), [grey] * 12)
        out = self._gate("flash", d, fps=24)
        self.assertEqual(out["transitions"], 0)
        self.assertTrue(out["passes_guideline"])

    def test_loop_identical_endpoints_close(self):
        a = np.random.default_rng(3).integers(0, 255, (48, 64, 3))
        b = np.random.default_rng(4).integers(0, 255, (48, 64, 3))
        d = write_frames(os.path.join(self.tmp, "loop"), [a, b, a])
        out = self._gate("loop", d)
        self.assertEqual(out["mean_abs_diff"], 0.0)
        self.assertTrue(out["loop_closed"])
        d2 = write_frames(os.path.join(self.tmp, "open"), [a, b])
        out2 = self._gate("loop", d2)
        self.assertGreater(out2["mean_abs_diff"], 0.05)
        self.assertFalse(out2["loop_closed"])
        self.assertIsNotNone(out2["changed_bbox"])

    def test_stats_constant_exposure_is_stable(self):
        grey = np.full((48, 64, 3), 100.0)
        d = write_frames(os.path.join(self.tmp, "stats"), [grey] * 8)
        out = self._gate("stats", d)
        self.assertEqual(out["temporal_std"], 0.0)
        self.assertEqual(out["exposure_drift"], 0.0)
        self.assertEqual(len(out["per_frame"]), 8)

    def test_stats_detects_exposure_drift(self):
        seq = [np.full((48, 64, 3), 40.0 + 20 * i) for i in range(6)]
        d = write_frames(os.path.join(self.tmp, "drift"), seq)
        out = self._gate("stats", d)
        self.assertGreater(out["exposure_drift"], 0.3)
        self.assertGreater(out["temporal_std"], 0.0)

    def test_safe_band_finds_detail_in_the_top_margin(self):
        frame = np.full((96, 128, 3), 200.0)
        frame[2:10, 20:100] = 0.0   # hard edges inside the top 12 % band
        d = write_frames(os.path.join(self.tmp, "band"), [frame] * 3)
        out = self._gate("safe_band", d)
        w = out["worst_detail_fraction"]
        self.assertGreater(w["top"], 0.5)
        self.assertLess(w["bottom"], 0.05)

    def test_unknown_gate_and_empty_dir_are_data(self):
        out = json.loads(tools.h_gate({"gate": "vibes", "frames_dir": self.tmp}))
        self.assertIn("unknown gate", out["error"])
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        out = json.loads(tools.h_gate({"gate": "flash", "frames_dir": empty}))
        self.assertIn("no numbered PNG", out["error"])

    def test_gate_and_script_are_mutually_exclusive(self):
        out = json.loads(tools.h_gate({"gate": "flash", "frames_dir": self.tmp,
                                       "script": "x.py"}))
        self.assertIn("not both", out["error"])

    def test_builtin_gates_are_approval_free_script_gates_prompt(self):
        self.assertIsNone(H.pre_tool_call("klieg_gate", {"gate": "flash", "frames_dir": "/x"}))
        self.assertIsNotNone(H.pre_tool_call("klieg_gate", {"script": "measure.py"}))


if __name__ == "__main__":
    unittest.main()