"""Publish must encode exactly the frames that exist.

Regression: image2 only probes start numbers 0-4, so a mid-sequence render
(frames 100-110) failed outright; a gapped set (0,2,4) silently encoded one
frame and reported exit 0 - the exact silent-partial-success class Klieg
exists to prevent. Contiguous runs now get -start_number, gapped sets get an
explicit concat list.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-pub-"))

import klieg_core as core
import klieg_tools as tools

HAVE_FFMPEG = bool(shutil.which("ffmpeg"))
try:
    from PIL import Image  # noqa: F401
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


def workdir(prefix):
    """A temp dir publish will accept. TMPDIR may point inside ~/.hermes on
    this host, which the write boundary correctly refuses; ~/.cache is outside
    every forbidden root on any profile."""
    base = os.path.join(os.path.expanduser("~"), ".cache", "klieg-tests")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix=prefix, dir=base)


def make_frames(directory, nums, size=(64, 64)):
    from PIL import Image
    os.makedirs(directory, exist_ok=True)
    for i in nums:
        Image.new("RGB", size, ((i * 37) % 255, 90, 140)).save(
            os.path.join(directory, f"{i:04d}.png"))


def drain(job, timeout=60):
    deadline = time.time() + timeout
    st = core.poll(job)
    while time.time() < deadline and st.get("state") in ("running", "queued"):
        time.sleep(0.2)
        st = core.poll(job)
    return st


def frame_count(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-count_frames", "-show_entries", "stream=nb_read_frames",
                          "-of", "csv=p=0", path], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class ArgvShape(unittest.TestCase):
    """No ffmpeg needed: assert the input shape handed to the job engine."""

    def setUp(self):
        self.tmp = workdir("klieg-pubargv-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "x.mp4")

    def _argv(self, nums):
        fd = os.path.join(self.tmp, f"f{nums[0]}_{nums[-1]}")
        make_frames(fd, nums)
        seen = {}
        fake = lambda name, argv, **kw: (seen.update(argv=argv, kw=kw),
                                         {"job": "pub-x", "state": "running"})[1]
        with mock.patch.object(core, "launch", side_effect=fake):
            res = json.loads(tools.h_publish({"frames_dir": fd, "out": self.out}))
        self.assertNotIn("error", res, res)
        return seen["argv"], seen["kw"], fd

    def test_mid_sequence_gets_start_number(self):
        argv, kw, _ = self._argv([100, 101, 102])
        self.assertIn("-start_number", argv)
        self.assertEqual(argv[argv.index("-start_number") + 1], "100")
        self.assertEqual(kw["meta"]["frame_count"], 3)
        self.assertFalse(kw["meta"]["gapped"])

    def test_gapped_set_uses_concat_with_every_frame(self):
        argv, kw, fd = self._argv([0, 2, 4])
        self.assertIn("concat", argv)
        self.assertTrue(kw["meta"]["gapped"])
        listfile = argv[argv.index("-i") + 1]
        with open(listfile) as f:
            content = f.read()
        for i in (0, 2, 4):
            self.assertIn(f"{i:04d}.png", content)
        self.assertEqual(content.count("duration"), 3)

    def test_contiguous_from_zero_still_pattern(self):
        argv, _, _ = self._argv([0, 1, 2])
        self.assertNotIn("concat", argv)
        self.assertEqual(argv[argv.index("-start_number") + 1], "0")

    def test_unnumbered_pngs_are_reported(self):
        fd = os.path.join(self.tmp, "unnumbered")
        os.makedirs(fd)
        from PIL import Image
        Image.new("RGB", (8, 8)).save(os.path.join(fd, "frame.png"))
        res = json.loads(tools.h_publish({"frames_dir": fd, "out": self.out}))
        self.assertIn("numbered", res["error"])


@unittest.skipUnless(HAVE_FFMPEG and HAVE_PIL, "ffmpeg/Pillow not available")
class RealEncode(unittest.TestCase):
    """The claim is about the file, so check the file: every frame survives."""

    def setUp(self):
        self.tmp = workdir("klieg-pubreal-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _encode_and_count(self, nums):
        fd = os.path.join(self.tmp, f"frames{nums[0]}")
        make_frames(fd, nums)
        out = os.path.join(self.tmp, f"out{nums[0]}.mp4")
        res = json.loads(tools.h_publish({"frames_dir": fd, "out": out, "fps": 24}))
        self.assertNotIn("error", res, res)
        st = drain(res["job"])
        self.assertEqual(st.get("state"), "done", core.tail(res["job"], 10))
        v = core.verify(res["job"])
        self.assertTrue(v["ok"], v)
        return frame_count(out)

    def test_mid_sequence_encodes_all_frames(self):
        self.assertEqual(self._encode_and_count([100, 101, 102]), 3)

    def test_gapped_set_encodes_all_frames(self):
        self.assertEqual(self._encode_and_count([0, 2, 4]), 3)


if __name__ == "__main__":
    unittest.main()