"""Plugin data is scoped to HERMES_HOME, not shared across profiles.

    python3 -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import types
import unittest
from unittest import mock

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
            marker = os.path.join(da, "jobs", "marker-a")
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            open(marker, "w").close()
            os.environ["HERMES_HOME"] = b
            db = core.data_dir()
            self.assertNotEqual(da, db)
            self.assertTrue(da.startswith(a))
            self.assertTrue(db.startswith(b))
            self.assertTrue(os.path.isfile(marker))
            self.assertFalse(os.path.exists(os.path.join(db, "jobs", "marker-a")))
        finally:
            if old_data is not None:
                os.environ["HERMES_PLUGIN_DATA"] = old_data
            if old_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = old_home

    def test_hermes_constants_home_is_used_when_available(self):
        # Review round 2: inside Hermes the profile-aware get_hermes_home()
        # is the source of truth, not a raw HERMES_HOME env read.
        home = tempfile.mkdtemp(prefix="klieg-const-home-")
        fake = types.ModuleType("hermes_constants")
        setattr(fake, "get_hermes_home", lambda: __import__("pathlib").Path(home))
        old_data = os.environ.pop("HERMES_PLUGIN_DATA", None)
        try:
            with mock.patch.dict(sys.modules, {"hermes_constants": fake}):
                d = core.data_dir()
            self.assertTrue(d.startswith(home), d)
        finally:
            if old_data is not None:
                os.environ["HERMES_PLUGIN_DATA"] = old_data

    def test_plugin_data_override_beats_hermes_constants(self):
        home = tempfile.mkdtemp(prefix="klieg-const-home2-")
        override = tempfile.mkdtemp(prefix="klieg-const-override-")
        fake = types.ModuleType("hermes_constants")
        setattr(fake, "get_hermes_home", lambda: __import__("pathlib").Path(home))
        old_data = os.environ.get("HERMES_PLUGIN_DATA")
        try:
            os.environ["HERMES_PLUGIN_DATA"] = override
            with mock.patch.dict(sys.modules, {"hermes_constants": fake}):
                d = core.data_dir()
            self.assertTrue(d.startswith(override), d)
        finally:
            if old_data is None:
                os.environ.pop("HERMES_PLUGIN_DATA", None)
            else:
                os.environ["HERMES_PLUGIN_DATA"] = old_data

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
