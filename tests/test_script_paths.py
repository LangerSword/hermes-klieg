"""Script input paths default to repo fixtures, not the author's machine."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from paths import FIXTURE_BLEND, resolve_input


class ScriptPaths(unittest.TestCase):
    def test_default_blend_is_repo_fixture(self):
        self.assertEqual(resolve_input("blend"), FIXTURE_BLEND)
        self.assertTrue(os.path.isfile(FIXTURE_BLEND))

    def test_cli_argument_wins(self):
        self.assertEqual(resolve_input("blend", FIXTURE_BLEND), FIXTURE_BLEND)

    def test_missing_path_has_clear_error(self):
        with self.assertRaises(SystemExit) as exc:
            resolve_input("blend", "/nonexistent/absent.blend")
        msg = str(exc.exception)
        self.assertIn("blend not found", msg)
        self.assertIn("KLIEG_BLEND", msg)


if __name__ == "__main__":
    unittest.main()
