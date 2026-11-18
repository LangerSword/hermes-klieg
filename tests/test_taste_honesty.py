"""Taste must report held-out accuracy, survive feature drift, and read 16-bit.

Regression: train() reported TRAINING accuracy while the module docstring
promised held-out; score() crashed with a numpy broadcast error when the model's
feature set drifted; normalization used a max-value heuristic that misread dark
16-bit frames.
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-taste-"))

try:
    import numpy as np
    from PIL import Image
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False

import klieg_taste as T


@unittest.skipUnless(HAVE_DEPS, "numpy/Pillow not installed")
class TasteHonesty(unittest.TestCase):
    def setUp(self):
        # Hermetic: other test files share this data dir and leave verdicts.
        for p in (T._store(), T._store().replace(".jsonl", ".model.json")):
            if os.path.exists(p):
                os.remove(p)
        self.tmp = tempfile.mkdtemp(prefix="klieg-th-")

    def _frame(self, kind="good"):
        import numpy as np
        from PIL import Image
        rng = np.random.default_rng(0 if kind == "good" else 1)
        h, w = 120, 68
        if kind == "good":
            arr = (np.linspace(12, 210, h)[:, None, None] * np.array([0.4, 0.55, 1.0])).repeat(w, 1)
            arr = arr + rng.normal(0, 4, (h, w, 3))
        else:
            arr = np.zeros((h, w, 3)) + rng.normal(0, 3, (h, w, 3))
            arr[: h // 3] = 255.0
        p = os.path.join(self.tmp, f"{kind}-{os.urandom(3).hex()}.png")
        Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(p)
        return p

    def _record_pairs(self, pairs):
        good, bad = self._frame("good"), self._frame("bad")
        for _ in range(pairs):
            T.record(good, True, "keep")
            T.record(bad, False, "reject")

    def test_accuracy_is_held_out_not_training(self):
        self._record_pairs(T.MIN_SAMPLES)
        t = T.train()
        self.assertTrue(t["trained"], t)
        self.assertIsNotNone(t["holdout_accuracy"])
        self.assertEqual(t["accuracy"], t["holdout_accuracy"])
        self.assertIn("train_accuracy", t)
        with open(T._store().replace(".jsonl", ".model.json")) as f:
            model = json.load(f)
        self.assertGreaterEqual(model["cv_folds"], 2)
        s = T.score(self._frame("good"))
        self.assertTrue(s["scored"])
        self.assertTrue(s["holdout"])
        self.assertEqual(s["accuracy"], model["acc"])

    def test_single_minority_verdict_is_labelled_unverified(self):
        good, bad = self._frame("good"), self._frame("bad")
        for _ in range(T.MIN_SAMPLES - 1):
            T.record(good, True, "keep")
        T.record(bad, False, "reject")
        t = T.train()
        self.assertTrue(t["trained"], t)
        self.assertIsNone(t["holdout_accuracy"])
        self.assertIn("unverified", t["holdout_note"])

    def test_score_refuses_feature_drift_instead_of_crashing(self):
        fake = {"mu": [0.0] * 3, "sd": [1.0] * 3, "w": [0.1] * 4,
                "names": ["a", "b", "c", "bias"], "n": 12, "acc": 0.9}
        with open(T._store().replace(".jsonl", ".model.json"), "w") as f:
            json.dump(fake, f)
        s = T.score(self._frame("good"))   # empty verdict store -> retrain refuses
        self.assertFalse(s["scored"])
        self.assertIn("feature set", s["error"])

    def test_dark_16bit_frame_is_not_reported_bright(self):
        import numpy as np
        from PIL import Image
        p = os.path.join(self.tmp, "dark16.png")
        Image.fromarray(np.full((32, 32), 1000, np.uint16)).save(p)
        f = T.features(p)
        self.assertLess(f["luma_median"], 0.05,
                        "a dark 16-bit frame must not normalize as 8-bit")


if __name__ == "__main__":
    unittest.main()