"""Plugin data is scoped to HERMES_HOME, not shared across profiles.

    python3 -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import klieg_core as core


class HomeIsolation(unittest.TestCase):
    def test_two_hermes_homes_do_not_share_jobs(self):
        a = tempfile.mkdtemp(prefix="klieg-home-a-")
        b = tempfile.mkdtemp(prefix="klieg-home-b-")
        old_data = os.environ.pop("HERMES_PLUGIN_DATA", None)
        old_home = os.environ.get("HERMES_HOME")
        try:
            os.environ["HERMES_HOME"] = a
            da = core.data_dir()
            os.environ["HERMES_HOME"] = b
            db = core.data_dir()
            self.assertNotEqual(da, db)
            self.assertTrue(da.startswith(a))
            self.assertTrue(db.startswith(b))
            self.assertFalse(os.path.exists(os.path.join(db, "jobs", "marker-a")))
        finally:
            if old_data is not None:
                os.environ["HERMES_PLUGIN_DATA"] = old_data
            if old_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = old_home

    def test_explicit_plugin_data_overrides_home(self):
        d = tempfile.mkdtemp(prefix="klieg-explicit-")
        old = os.environ.get("HERMES_PLUGIN_DATA")
        try:
            os.environ["HERMES_PLUGIN_DATA"] = d
            self.assertTrue(core.data_dir().startswith(d))
        finally:
            if old is None:
                os.environ.pop("HERMES_PLUGIN_DATA", None)
            else:
                os.environ["HERMES_PLUGIN_DATA"] = old


if __name__ == "__main__":
    unittest.main()
