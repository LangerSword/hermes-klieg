"""Install-surface tests: the plugin must not look like an editable Python package.

    python3 -m unittest discover -s tests -v

Hermes's PM resolver reads pyproject.toml first. An authored one at the plugin root with no
buildable distribution makes `plugins enable` fail with "Distribution not found for the editable
hermes-klieg package". Dependencies belong in plugin.yaml instead.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class Packaging(unittest.TestCase):
    def test_no_pyproject_at_plugin_root(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "pyproject.toml")),
                         "pyproject.toml makes Hermes treat the plugin as an editable package")

    def test_runtime_dependencies_declared_in_manifest(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not available in this interpreter")
        with open(os.path.join(ROOT, "plugin.yaml")) as f:
            m = yaml.safe_load(f)
        deps = [str(d).lower() for d in (m.get("python_dependencies") or [])]
        self.assertTrue(any(d.startswith("numpy") for d in deps), deps)
        self.assertTrue(any(d.startswith("pillow") or d.startswith("pil") for d in deps), deps)


if __name__ == "__main__":
    unittest.main()
