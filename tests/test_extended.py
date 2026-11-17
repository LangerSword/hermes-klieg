"""Tests for the live bridge, colour manifest and taste model.

    python3 -m unittest discover -s tests -v

No Blender needed: the bridge is tested against a fake unix-socket host that speaks the
same protocol, and the real-Blender proof lives in scripts/test_bridge.py.
"""

import json
import os
import socket
import tempfile
import threading
import time
import unittest

os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-tests-"))

import klieg_bridge as B
import klieg_colour as C
import klieg_taste as T


# ------------------------------------------------------------------ fake host
class FakeHost(threading.Thread):
    """Answers the wire protocol without Blender, so the client can be tested for real."""

    def __init__(self, path, delay=0.0, close_without_reply=False):
        super().__init__(daemon=True)
        self.path = path
        self.delay = delay
        self.close_without_reply = close_without_reply
        self.stop = False
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if os.path.exists(path):
            os.unlink(path)
        self.srv.bind(path)
        self.srv.listen(4)
        self.srv.settimeout(0.2)

    def run(self):
        while not self.stop:
            try:
                conn, _ = self.srv.accept()
            except socket.timeout:
                continue
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
            if self.close_without_reply:
                conn.close()
                continue
            try:
                req = json.loads(buf.decode() or "{}")
                time.sleep(self.delay)
                op = req.get("op")
                if op == "ping":
                    res = {"ok": True, "result": "pong"}
                elif op == "info":
                    res = {"ok": True, "result": json.dumps({"blender": "5.3.0", "objects": 3})}
                elif op == "eval":
                    res = {"ok": True, "result": "4"}
                else:
                    res = {"ok": False, "error": "unknown op"}
                res["id"] = req.get("id", 0)
                try:
                    conn.sendall((json.dumps(res) + "\n").encode())
                except OSError:
                    pass          # the client gave up (that is what the timeout test does)
            finally:
                conn.close()

    def shutdown(self):
        self.stop = True
        self.join(timeout=2)
        self.srv.close()
        if os.path.exists(self.path):
            os.unlink(self.path)


class BridgeClient(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="klieg-sock-")
        self.path = os.path.join(self.dir, "s.sock")

    def test_ping_info_eval(self):
        h = FakeHost(self.path)
        h.start()
        try:
            b = B.Bridge(self.path, timeout=5)
            self.assertEqual(b.ping()["result"], "pong")
            self.assertIn("5.3.0", b.info()["result"])
            self.assertEqual(b.eval(expr="1")["result"], "4")
        finally:
            h.shutdown()

    def test_missing_socket_raises_unavailable(self):
        b = B.Bridge(os.path.join(self.dir, "nope.sock"))
        with self.assertRaises(B.BridgeUnavailable):
            b.ping()

    def test_silent_host_raises_timeout_not_hang(self):
        h = FakeHost(self.path, delay=2.0)
        h.start()
        try:
            b = B.Bridge(self.path, timeout=0.4)
            t0 = time.time()
            with self.assertRaises(B.BridgeTimeout):
                b.ping()
            self.assertLess(time.time() - t0, 1.5, "timeout must fire promptly")
        finally:
            h.shutdown()

    def test_host_closing_without_reply_is_reported(self):
        h = FakeHost(self.path, close_without_reply=True)
        h.start()
        try:
            b = B.Bridge(self.path, timeout=2)
            with self.assertRaises(B.BridgeUnavailable):
                b.ping()
        finally:
            h.shutdown()


class Colour(unittest.TestCase):
    def test_compare_flags_a_view_transform_change(self):
        a = {"view_transform": "Khronos PBR Neutral", "look": "None", "exposure": -1.0}
        b = {"view_transform": "AgX", "look": "None", "exposure": -1.0}
        diffs = C.compare(a, b)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]["field"], "view_transform")
        self.assertEqual(diffs[0]["actual"], "AgX")

    def test_identical_manifests_are_the_same_film(self):
        a = {"view_transform": "AgX", "exposure": 0.0}
        self.assertEqual(C.compare(a, dict(a)), [])

    def test_manifest_round_trip_and_ocio_hash(self):
        d = tempfile.mkdtemp(prefix="klieg-colour-")
        p = C.write(d, {"view_transform": "AgX", "exposure": -1.0})
        self.assertTrue(os.path.exists(p))
        back = C.read(d)
        self.assertEqual(back["view_transform"], "AgX")
        self.assertIn("ocio_config_sha256", back)


class Taste(unittest.TestCase):
    def _frame(self, kind="good"):
        """Synthetic frames that differ in the ways the features care about."""
        from PIL import Image
        import numpy as np
        rng = np.random.default_rng(0 if kind == "good" else 1)
        h, w = 240, 135
        if kind == "good":
            arr = (np.linspace(12, 210, h)[:, None, None] * np.array([0.4, 0.55, 1.0])).repeat(w, 1)
            arr = arr + rng.normal(0, 4, (h, w, 3))
        else:
            arr = np.zeros((h, w, 3)) + rng.normal(0, 3, (h, w, 3))
            arr[: h // 3] = 255.0
        d = tempfile.mkdtemp(prefix="klieg-taste-")
        p = os.path.join(d, f"{kind}.png")
        Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(p)
        return p

    def test_features_are_numbers_and_differ_by_frame(self):
        good = T.features(self._frame("good"))
        bad = T.features(self._frame("bad"))
        self.assertTrue(all(isinstance(v, float) for v in good.values()))
        self.assertGreater(abs(good["contrast"] - bad["contrast"]), 0.1)
        self.assertGreater(bad["clip_hi"], good["clip_hi"])

    def test_refuses_to_score_without_verdicts(self):
        out = T.train()
        self.assertFalse(out["trained"])
        self.assertIn("need", out)

    def test_records_verdicts_and_still_refuses_below_threshold(self):
        good = self._frame("good")
        bad = self._frame("bad")
        T.record(good, True, "holds together")
        T.record(bad, False, "blown highlights")
        out = T.train()
        self.assertFalse(out["trained"])
        self.assertGreaterEqual(out["n"], 2)

    def test_trains_and_scores_once_there_is_signal(self):
        store = T._store()
        if os.path.exists(store):
            os.remove(store)
        model = store.replace(".jsonl", ".model.json")
        if os.path.exists(model):
            os.remove(model)
        good, bad = self._frame("good"), self._frame("bad")
        for i in range(T.MIN_SAMPLES):
            T.record(good, True, "keep")
            T.record(bad, False, "reject")
        t = T.train()
        self.assertTrue(t["trained"], t)
        self.assertGreater(t["accuracy"], 0.8)
        s = T.score(good)
        self.assertTrue(s["scored"])
        self.assertGreaterEqual(s["p_accept"], 0.5)
        self.assertTrue(s["why"])
        self.assertIn("caveat", s)


if __name__ == "__main__":
    unittest.main()
