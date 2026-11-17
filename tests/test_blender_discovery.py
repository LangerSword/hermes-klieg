"""Blender discovery uses KLIEG_BLENDER first, then PATH.

    python3 -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", tempfile.mkdtemp(prefix="klieg-discover-"))

import klieg_adapters as A


class BlenderDiscovery(unittest.TestCase):
    def test_override_wins(self):
        fixture = os.path.join(ROOT, "tests", "fixtures", "fake_blender")
        old = os.environ.get("KLIEG_BLENDER")
        try:
            os.environ["KLIEG_BLENDER"] = fixture
            self.assertEqual(A.Blender().find_binary(), fixture)
            # A real override still gets a real version probe, never a fake label.
            with mock.patch.object(A.core, "run_child") as run:
                run.return_value = mock.Mock(stdout="Blender 4.2.0\n", stderr="")
                self.assertIn("4.2", A.Blender().detect()["version"])
        finally:
            if old is None:
                os.environ.pop("KLIEG_BLENDER", None)
            else:
                os.environ["KLIEG_BLENDER"] = old

    def test_fixture_is_executable(self):
        fixture = os.path.join(ROOT, "tests", "fixtures", "fake_blender")
        self.assertTrue(os.access(fixture, os.X_OK))


if __name__ == "__main__":
    unittest.main()
