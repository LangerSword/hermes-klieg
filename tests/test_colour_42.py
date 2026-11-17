"""Colour probe must read display_device from display_settings, not view_settings.

    python3 -m unittest discover -s tests -v

Blender 4.2 has no view_settings.display_device. The probe script is executed against
a fake bpy so the exact access is tested without launching Blender.
"""

import io
import json
import os
import sys
import types
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HERMES_PLUGIN_DATA", "/tmp/klieg-colour-test")
os.makedirs("/tmp/klieg-colour-test", exist_ok=True)

import klieg_colour as C


class ViewSettings:
    view_transform = "AgX"
    look = "None"
    exposure = 0.0
    gamma = 1.0
    use_curve_mapping = False
    # deliberately NO display_device attribute (Blender 4.2)


class DisplaySettings:
    display_device = "sRGB"


class ImageSettings:
    file_format = "PNG"
    color_depth = "8"


class Render:
    film_transparent = False
    image_settings = ImageSettings()


class Scene:
    view_settings = ViewSettings()
    display_settings = DisplaySettings()
    sequencer_colorspace_settings = types.SimpleNamespace(name="sRGB")
    render = Render()


class FakeBpy:
    class Data:
        filepath = "/tmp/fake.blend"

    class App:
        version_string = "4.2.0"

    class Utils:
        @staticmethod
        def resource_path(kind):
            return "/tmp/fake-blender-resources"

    class Preferences:
        studio_lights = []

    preferences = Preferences()
    context = types.SimpleNamespace(scene=Scene(), preferences=preferences)
    data = Data()
    app = App()
    utils = Utils()
    preferences = Preferences()


class ColourProbe(unittest.TestCase):
    def test_probe_reads_display_device_from_display_settings(self):
        buf = io.StringIO()
        fake = types.ModuleType("bpy")
        for k, v in vars(FakeBpy).items():
            if not k.startswith("__"):
                setattr(fake, k, v)
        old = sys.modules.get("bpy")
        sys.modules["bpy"] = fake
        try:
            with redirect_stdout(buf):
                exec(C.PROBE, {})
        finally:
            if old is None:
                sys.modules.pop("bpy", None)
            else:
                sys.modules["bpy"] = old
        line = next(l for l in buf.getvalue().splitlines() if l.startswith("KLIIEG_COLOUR "))
        manifest = json.loads(line.split(" ", 1)[1])
        self.assertEqual(manifest["display_device"], "sRGB")
        self.assertEqual(manifest["view_transform"], "AgX")

    def test_probe_source_does_not_touch_view_settings_display_device(self):
        self.assertNotIn("vs.display_device", C.PROBE)
        self.assertIn("sc.display_settings", C.PROBE)


if __name__ == "__main__":
    unittest.main()
