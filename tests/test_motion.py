"""klieg_motion: the 2D motion-design engine.

Hermes authors a scene (declarative spec or raw HTML+GSAP); klieg compiles it to
an HTML+GSAP film and renders it to MP4/GIF. These tests cover the compiler and
templates (no browser needed); the real render is exercised separately under a
Playwright guard.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", __import__("tempfile").mkdtemp(prefix="klieg-motion-"))

import klieg_motion as M


class CompileScene(unittest.TestCase):
    def _spec(self, **over):
        spec = {
            "width": 1920, "height": 1080, "fps": 30, "duration": 6,
            "background": {"color": "#070605"},
            "layers": [
                {"id": "title", "type": "text", "text": "KLIEG", "x": 96, "y": 500,
                 "size": 200, "font": "display", "color": "#ece4d6",
                 "animate": [{"effect": "rise", "start": 0.2, "duration": 0.9,
                              "ease": "expo.out", "stagger": 0.08, "split": "char"}]},
            ],
        }
        spec.update(over)
        return spec

    def test_compile_emits_text_timeline_and_hook(self):
        html = M.compile_scene(self._spec())
        # char-split breaks "KLIEG" into spans; assert the glyphs are present
        self.assertIn(">K</span>", html)
        self.assertIn(">G</span>", html)
        self.assertIn('id="title"', html)
        self.assertIn("window.__tl", html)
        self.assertIn("gsap", html)
        self.assertIn("expo.out", html)

    def test_stagger_split_wraps_chars_in_spans(self):
        html = M.compile_scene(self._spec())
        # KLIEG = 5 chars -> at least 5 inline-block spans for the stagger
        self.assertGreaterEqual(html.count("<span"), 5)
        self.assertIn("stagger", html)

    def test_background_color_is_applied(self):
        html = M.compile_scene(self._spec())
        self.assertIn("#070605", html)

    def test_rejects_empty_layers(self):
        with self.assertRaises(ValueError):
            M.compile_scene(self._spec(layers=[]))

    def test_rejects_unknown_effect(self):
        spec = self._spec()
        spec["layers"][0]["animate"][0]["effect"] = "teleport"
        with self.assertRaises(ValueError):
            M.compile_scene(spec)

    def test_rejects_text_layer_without_text(self):
        spec = self._spec()
        del spec["layers"][0]["text"]
        with self.assertRaises(ValueError):
            M.compile_scene(spec)

    def test_defaults_fill_missing_dimensions(self):
        html = M.compile_scene({"layers": [{"id": "a", "type": "text", "text": "hi",
                                            "animate": [{"effect": "fade"}]}]})
        self.assertIn("1920", html)
        self.assertIn("1080", html)


class Templates(unittest.TestCase):
    def test_title_reveal_template_compiles(self):
        spec = M.template("title-reveal", word="KLIEG", tagline="motion for Hermes")
        html = M.compile_scene(spec)
        self.assertIn(">K</span>", html)          # word is char-split
        self.assertIn("motion for Hermes", html)  # tagline is not split

    def test_lower_third_template_compiles(self):
        spec = M.template("lower-third", name="Ada Lovelace", role="Engineer")
        html = M.compile_scene(spec)
        self.assertIn("Ada Lovelace", html)
        self.assertIn("Engineer", html)

    def test_kinetic_quote_template_compiles(self):
        spec = M.template("kinetic-quote", quote="Truth is the artefact.", by="Klieg")
        html = M.compile_scene(spec)
        self.assertIn("artefact.", html)  # word-split, each word in a span
        self.assertIn("- Klieg", html)

    def test_list_templates_describes_each(self):
        listed = M.list_templates()
        names = {t["name"] for t in listed}
        self.assertIn("title-reveal", names)
        self.assertIn("lower-third", names)
        for t in listed:
            self.assertTrue(t.get("description"))

    def test_unknown_template_raises(self):
        with self.assertRaises(ValueError):
            M.template("does-not-exist")


import json
import shutil
import time
from unittest import mock
import klieg_core as core
import klieg_tools as tools
import klieg_hooks as hooks


def _call(args):
    return json.loads(tools.h_motion(args))


class MotionHandler(unittest.TestCase):
    def test_templates_action_lists_starters_and_effects(self):
        out = _call({"action": "templates"})
        self.assertTrue(any(t["name"] == "title-reveal" for t in out["templates"]))
        self.assertIn("rise", out["effects"])

    def test_unknown_action_is_data(self):
        self.assertIn("error", _call({"action": "teleport"}))

    def test_render_requires_out(self):
        self.assertIn("error", _call({"action": "render", "template": "title-reveal"}))

    def test_render_refuses_credential_out(self):
        out = _call({"action": "render", "template": "title-reveal", "out": "~/.ssh/x.mp4"})
        self.assertIn("refusing", out["error"])

    def test_render_bad_template_is_data(self):
        out = _call({"action": "render", "template": "nope", "out": "/tmp/x.mp4"})
        self.assertIn("error", out)

    def test_render_launches_job_with_engine_argv(self):
        seen = {}
        fake = lambda name, argv, **kw: (seen.update(argv=argv, kw=kw),
                                         {"job": "motion-x", "state": "running"})[1]
        with mock.patch.object(core, "launch", side_effect=fake):
            out = _call({"action": "render", "template": "title-reveal",
                         "params": {"word": "HI"}, "out": "/tmp/klieg-m/x.mp4", "format": "gif"})
        self.assertEqual(out["job"], "motion-x")
        self.assertIn("motion_render.py", " ".join(seen["argv"]))
        self.assertIn("--format", seen["argv"])
        self.assertEqual(seen["kw"]["meta"]["format"], "gif")
        self.assertEqual(seen["kw"]["guard"], ["/tmp/klieg-m/x.mp4"])

    def test_approval_policy(self):
        self.assertIsNone(hooks.pre_tool_call("klieg_motion", {"action": "templates"}))
        for act in ("render", "preview"):
            r = hooks.pre_tool_call("klieg_motion", {"action": act})
            assert r is not None, act
            self.assertEqual(r["rule_key"], "klieg:klieg_motion")


def _have_playwright():
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_have_playwright() and shutil.which("ffmpeg"),
                     "playwright/ffmpeg not available")
class MotionRealRender(unittest.TestCase):
    def test_template_renders_to_verified_mp4(self):
        base = os.path.join(os.path.expanduser("~"), ".cache", "klieg-motion-test")
        os.makedirs(base, exist_ok=True)
        out = os.path.join(base, f"title-{os.urandom(3).hex()}.mp4")
        res = _call({"action": "render", "template": "title-reveal",
                     "params": {"word": "KLIEG", "tagline": "motion for Hermes"},
                     "out": out, "fps": 12})
        self.assertIn("job", res, res)
        job = res["job"]
        deadline = time.time() + 240
        st = core.poll(job)
        while st.get("state") == "running" and time.time() < deadline:
            time.sleep(1)
            st = core.poll(job)
        self.assertEqual(st.get("state"), "done", core.tail(job, 12))
        v = core.verify(job)
        self.assertTrue(v["ok"], v)
        self.assertTrue(os.path.exists(out))
        self.assertGreater(os.path.getsize(out), 1000)


if __name__ == "__main__":
    unittest.main()