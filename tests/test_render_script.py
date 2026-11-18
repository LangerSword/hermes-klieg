"""The generated render script: unique per render, safe for any path.

Regression: a fixed script name next to outdir meant two renders into sibling
directories overwrote each other's script (the first job rendered the second
job's frames), and raw string interpolation broke on paths with quotes.
"""

import ast
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-script-"))

import klieg_adapters as A
import klieg_core as core


def literal(script_path, name):
    """Read a top-level assignment's literal value out of the generated script."""
    with open(script_path) as f:
        tree = ast.parse(f.read(), script_path)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not assigned in {script_path}")


class RenderScript(unittest.TestCase):
    def setUp(self):
        self.ad = A.Blender()
        self.tmp = tempfile.mkdtemp(prefix="klieg-rs-")

    def test_two_renders_get_distinct_scripts_with_their_own_frames(self):
        a1 = self.ad.render_argv([0, 1], os.path.join(self.tmp, "a"), 32, 25, "s.blend")
        a2 = self.ad.render_argv([5, 6], os.path.join(self.tmp, "b"), 32, 25, "s.blend")
        s1, s2 = a1[a1.index("-P") + 1], a2[a2.index("-P") + 1]
        self.assertNotEqual(s1, s2, "concurrent renders must not share a script")
        self.assertEqual(literal(s1, "FRAMES"), [0, 1])
        self.assertEqual(literal(s2, "FRAMES"), [5, 6])
        # confined to the plugin data dir, not the user's output tree
        self.assertTrue(s1.startswith(core.data_dir()))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "_klieg_render.py")))

    def test_path_with_quotes_and_spaces_round_trips(self):
        nasty = os.path.join(self.tmp, 'we"ird dir', "sub'\\dir")
        argv = self.ad.render_argv([3], nasty, 16, 50, "s.blend")
        script = argv[argv.index("-P") + 1]
        with open(script) as f:
            compile(f.read(), script, "exec")   # must be valid Python
        self.assertEqual(literal(script, "OUT"), nasty)
        self.assertEqual(literal(script, "FRAMES"), [3])

    def test_dry_resolves_argv_without_writing(self):
        argv = self.ad.render_argv([0], os.path.join(self.tmp, "d"), 8, 100, "s.blend", dry=True)
        script = argv[argv.index("-P") + 1]
        self.assertFalse(os.path.exists(script))
        self.assertIn("_klieg_render_", script)

    def test_script_compiles_for_eevee_scenes_too(self):
        # cycles settings are guarded: an EEVEE scene without the cycles
        # property must not crash the render script.
        argv = self.ad.render_argv([0], os.path.join(self.tmp, "e"), 8, 100, "s.blend")
        with open(argv[argv.index("-P") + 1]) as f:
            src = f.read()
        self.assertIn('hasattr(sc, "cycles")', src)
        compile(src, "render.py", "exec")


if __name__ == "__main__":
    unittest.main()