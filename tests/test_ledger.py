"""The shot ledger: seal, then prove nothing drifted.

The claim under test: after sealing, a changed frame, a deleted frame, an added
frame, an edited scene, a swapped colour manifest, or a touched-up encode is
REPORTED, and an untouched chain verifies intact. No Blender needed - the jobs
are shell children writing real files.
"""

import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-ledger-"))

import klieg_core as core
import klieg_ledger as L
import klieg_hooks as H
import klieg_tools as tools


def drain(job, timeout=10):
    deadline = time.time() + timeout
    st = core.poll(job)
    while time.time() < deadline and st.get("state") in ("running", "queued"):
        time.sleep(0.05)
        st = core.poll(job)
    return st


class Ledger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="klieg-lg-")
        self.frames = os.path.join(self.tmp, "frames")
        os.makedirs(self.frames)
        self.blend = os.path.join(self.tmp, "scene.blend")
        with open(self.blend, "w") as f:
            f.write("scene-v1")
        # A real detached job that writes two frames, like a render would.
        cmd = (f"printf frame0 > {self.frames}/0000.png; "
               f"printf frame1 > {self.frames}/0001.png")
        self.job = core.launch("shot", ["/bin/sh", "-c", cmd],
                               guard=[os.path.join(self.frames, "0000.png")],
                               expect={"dir": self.frames, "min": 2, "ext": ".png"},
                               frames=2, meta={"blend": self.blend})["job"]
        st = drain(self.job)
        self.assertEqual(st["state"], "done", st)

    def test_seal_requires_a_done_job(self):
        j = core.launch("slow", ["/bin/sh", "-c", "sleep 5"])["job"]
        try:
            r = L.seal(j)
            self.assertFalse(r["ok"])
            self.assertIn("not done", r["error"])
        finally:
            core.kill(j)
            drain(j)

    def test_seal_check_intact_chain(self):
        r = L.seal(self.job)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["frames"], 2)
        self.assertEqual(len(r["ledger_root"]), 64)
        c = L.check(self.job)
        self.assertTrue(c["intact"], c)
        self.assertEqual(c["changed"], [])
        self.assertEqual(c["missing"], [])
        self.assertEqual(c["added_frames"], [])
        s = L.show(self.job)
        self.assertTrue(s["ok"])
        self.assertEqual(s["scene"]["sha256"], r["scene"])

    def test_tampered_frame_is_reported(self):
        L.seal(self.job)
        with open(os.path.join(self.frames, "0001.png"), "w") as f:
            f.write("retouched")
        c = L.check(self.job)
        self.assertFalse(c["intact"])
        self.assertEqual(len(c["changed"]), 1)
        self.assertEqual(c["changed"][0]["what"], "frame")

    def test_deleted_and_added_frames_are_reported(self):
        L.seal(self.job)
        os.remove(os.path.join(self.frames, "0000.png"))
        with open(os.path.join(self.frames, "0002.png"), "w") as f:
            f.write("extra")
        c = L.check(self.job)
        self.assertFalse(c["intact"])
        self.assertEqual(len(c["missing"]), 1)
        self.assertEqual(len(c["added_frames"]), 1)

    def test_edited_scene_is_reported(self):
        L.seal(self.job)
        with open(self.blend, "w") as f:
            f.write("scene-v2")
        c = L.check(self.job)
        self.assertFalse(c["intact"])
        self.assertEqual(c["changed"][0]["what"], "scene")

    def test_colour_manifest_is_part_of_the_seal(self):
        mp = os.path.join(self.frames, "colour_manifest.json")
        with open(mp, "w") as f:
            json.dump({"view_transform": "AgX"}, f)
        L.seal(self.job)
        with open(mp, "w") as f:
            json.dump({"view_transform": "Khronos PBR Neutral"}, f)
        c = L.check(self.job)
        self.assertFalse(c["intact"])
        self.assertEqual(c["changed"][0]["what"], "colour_manifest")

    def test_publish_links_back_to_source_frames(self):
        out = os.path.join(self.tmp, "film.mp4")
        pub = core.launch("publish", ["/bin/sh", "-c", f"printf encoded > {out}"],
                          guard=[out],
                          meta={"frames_dir": self.frames, "frame_count": 2})["job"]
        self.assertEqual(drain(pub)["state"], "done")
        r = L.seal(pub)
        self.assertTrue(r["ok"], r)
        self.assertTrue(L.check(pub)["intact"])
        # Drift in the SOURCE frames breaks the publish seal too.
        with open(os.path.join(self.frames, "0000.png"), "w") as f:
            f.write("different")
        c = L.check(pub)
        self.assertFalse(c["intact"])
        self.assertTrue(c["source_frames_changed"])

    def test_unsealed_job_is_reported_not_raised(self):
        self.assertFalse(L.check(self.job)["ok"])
        self.assertFalse(L.show(self.job)["ok"])
        self.assertFalse(L.seal("../escape")["ok"])

    def test_tool_surface_and_policy(self):
        r = json.loads(tools.h_ledger({"action": "seal", "job": self.job}))
        self.assertTrue(r["ok"], r)
        self.assertIsNone(H.pre_tool_call("klieg_ledger", {"action": "check", "job": self.job}))
        self.assertIsNone(H.pre_tool_call("klieg_ledger", {"action": "show", "job": self.job}))
        gate = H.pre_tool_call("klieg_ledger", {"action": "seal", "job": self.job})
        self.assertIsNotNone(gate)
        names = [s["name"] for s in tools.TOOL_SPECS]
        self.assertIn("klieg_ledger", names)


if __name__ == "__main__":
    unittest.main()