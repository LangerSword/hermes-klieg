"""Motion frames must never empty a pre-existing user directory.

Review round 2 regression: frames were rendered into out.parent/(out.stem +
"_frames") and EVERY file in that directory was deleted before and after the
render. A user folder that happened to carry that name was emptied. Frames
now go into a fresh, unique temp dir under the plugin data dir, removed after
the encode.

The wiring tests stub the browser and the encoder so they run everywhere CI
runs; the real-render test exercises the full path where playwright + ffmpeg
exist.
"""

import importlib.machinery
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-workdir-"))

import klieg_core as core
import motion_render as MR


def _fake_playwright():
    """main() only checks that playwright imports; the render is stubbed."""
    m = types.ModuleType("playwright")
    m.__spec__ = importlib.machinery.ModuleSpec("playwright", None)
    return m


class WorkDirPolicy(unittest.TestCase):
    def setUp(self):
        base = os.path.join(os.path.expanduser("~"), ".cache", "klieg-tests")
        os.makedirs(base, exist_ok=True)
        self.tmp = tempfile.mkdtemp(prefix="klieg-wd-", dir=base)
        self.html = os.path.join(self.tmp, "scene.html")
        with open(self.html, "w") as f:
            f.write("<html><body>scene</body></html>")
        self.out = os.path.join(self.tmp, "clip.mp4")
        # A user folder that happens to match the OLD work-dir name.
        self.sentinel_dir = os.path.join(self.tmp, "clip_frames")
        os.makedirs(self.sentinel_dir)
        self.sentinel = os.path.join(self.sentinel_dir, "keep.txt")
        with open(self.sentinel, "w") as f:
            f.write("precious")

    def _run(self, encode=None):
        argv = ["motion_render.py", self.html, self.out,
                "--fps", "10", "--duration", "0.2", "--width", "64", "--height", "64"]
        if encode is None:
            def encode(frames, out, fps, music, duration):
                Path(out).write_bytes(b"fake-mp4")  # the real encoder produces `out`
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.dict(sys.modules, {"playwright": _fake_playwright()}), \
             mock.patch.object(MR, "to_mp4", side_effect=encode) as enc:
            rc = MR.main()
        return rc, enc

    def test_frames_go_to_a_fresh_dir_under_the_plugin_data_dir(self):
        seen = {}

        def fake_render(html, frames, fps, duration, w, h):
            seen["frames"] = frames
            (frames / "0000.png").write_bytes(b"x")
            return 1

        with mock.patch.object(MR, "render_frames", side_effect=fake_render):
            rc, enc = self._run()
        self.assertEqual(rc, 0)
        work = seen["frames"]
        self.assertTrue(str(work).startswith(core.data_dir()), work)
        self.assertNotEqual(str(work), self.sentinel_dir)
        self.assertTrue(os.path.isfile(self.sentinel), "the user's folder must survive")
        with open(self.sentinel) as f:
            self.assertEqual(f.read(), "precious")
        self.assertFalse(work.exists(), "the private work dir is cleaned after the encode")
        enc.assert_called_once()

    def test_two_renders_do_not_share_a_work_dir(self):
        seen = []

        def fake_render(html, frames, fps, duration, w, h):
            seen.append(frames)
            (frames / "0000.png").write_bytes(b"x")
            return 1

        with mock.patch.object(MR, "render_frames", side_effect=fake_render):
            self._run()
            self._run()
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0], seen[1])

    def test_work_dir_is_cleaned_even_when_the_encode_fails(self):
        seen = {}

        def fake_render(html, frames, fps, duration, w, h):
            seen["frames"] = frames
            (frames / "0000.png").write_bytes(b"x")
            return 1

        def bad_encode(frames, out, fps, music, duration):
            raise RuntimeError("ffmpeg died")

        with mock.patch.object(MR, "render_frames", side_effect=fake_render):
            with self.assertRaises(RuntimeError):
                self._run(encode=bad_encode)
        self.assertFalse(seen["frames"].exists(), "no orphan frame dir after a failed encode")
        self.assertTrue(os.path.isfile(self.sentinel))


def _have_playwright():
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_have_playwright() and shutil.which("ffmpeg"),
                     "playwright/ffmpeg not available")
class RealRenderSentinel(unittest.TestCase):
    def test_existing_frames_folder_survives_a_real_render(self):
        base = os.path.join(os.path.expanduser("~"), ".cache", "klieg-tests")
        os.makedirs(base, exist_ok=True)
        tmp = tempfile.mkdtemp(prefix="klieg-wd-real-", dir=base)
        html = os.path.join(tmp, "scene.html")
        with open(html, "w") as f:
            f.write("<html><body style='background:#111;color:#eee'>scene</body></html>")
        out = os.path.join(tmp, "clip.mp4")
        sentinel_dir = os.path.join(tmp, "clip_frames")
        os.makedirs(sentinel_dir)
        sentinel = os.path.join(sentinel_dir, "keep.txt")
        with open(sentinel, "w") as f:
            f.write("precious")
        argv = ["motion_render.py", html, out,
                "--fps", "10", "--duration", "0.2", "--width", "64", "--height", "64"]
        with mock.patch.object(sys, "argv", argv):
            rc = MR.main()
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(out))
        self.assertGreater(os.path.getsize(out), 0)
        self.assertTrue(os.path.isfile(sentinel), "a real render must not empty clip_frames/")
        with open(sentinel) as f:
            self.assertEqual(f.read(), "precious")


if __name__ == "__main__":
    unittest.main()
