"""Colour management that means something.

Tags are the floor: BT.709 primaries and a transfer in the container stop a phone from
guessing. But a render is also only correct relative to the *scene's* colour management, and
the same scene rendered under a different view transform is a different film. So Klieg
records a manifest next to the frames and a gate can assert it:

    board/colour_manifest.json   display device, view transform, look, exposure, gamma,
                                 OCIO config path + its sha256, sequencer/curve settings

`klieg_colour` can read the live scene (through the bridge or a batch probe), diff a
manifest against the current scene, and verify that a delivered encode carries the tags it
claims. The point is to catch the silent failure: someone re-renders with AgX instead of
Khronos PBR Neutral and every frame is subtly wrong while every gate still passes.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess

try:  # loaded as a Hermes plugin package
    from . import klieg_core as core
except ImportError:  # loaded standalone (tests, scripts)
    import klieg_core as core

MANIFEST = "colour_manifest.json"

PROBE = r"""
import bpy, json, hashlib, os
vs = bpy.context.scene.view_settings
sc = bpy.context.scene
cfg = bpy.context.preferences.studio_lights  # touch, keeps the context alive
try:
    ocio = bpy.utils.resource_path('LOCAL')
except Exception:
    ocio = ''
manifest = {
  "display_device": getattr(sc.display_settings, "display_device", ""),
  "view_transform": vs.view_transform,
  "look": vs.look,
  "exposure": round(float(vs.exposure), 4),
  "gamma": round(float(vs.gamma), 4),
  "sequencer_colorspace": getattr(sc.sequencer_colorspace_settings, "name", ""),
  "curve_mapping": bool(vs.use_curve_mapping),
  "view_settings_use_curve": bool(getattr(vs, "use_curve_mapping", False)),
  "ocio_resource_path": ocio,
  "display_settings": getattr(sc.display_settings, "display_device", ""),
  "applied_view_settings": getattr(sc.view_settings, "view_transform", ""),
  "film_transparent": bool(sc.render.film_transparent),
  "file_format": sc.render.image_settings.file_format,
  "color_depth": sc.render.image_settings.color_depth,
}
print("KLIIEG_COLOUR " + json.dumps(manifest))
"""


def sha256_of(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def find_ocio_config() -> str | None:
    """Blender ships its config inside the resource dir; OCIO can also be overridden."""
    env = os.environ.get("OCIO")
    if env and os.path.exists(env):
        return env
    for base in ("/usr/share/blender", "/usr/local/blender", "/opt/blender"):
        for root, _dirs, files in os.walk(base):
            if "config.ocio" in files:
                return os.path.join(root, "config.ocio")
    return None


def probe_batch(blender: str, blend: str, timeout: int = 120) -> dict:
    """Read colour state from a headless Blender without opening a session."""
    script = "/tmp/klieg_colour_probe.py"
    with open(script, "w") as f:
        f.write(PROBE)
    extra = {"PATH": "/usr/bin:/bin"}
    if os.environ.get("OCIO"):
        extra["OCIO"] = os.environ["OCIO"]
    p = core.run_child([blender, "-b", blend, "-P", script],
                       timeout=timeout, extra_env=extra)
    for line in (p.stdout or "").splitlines():
        if line.startswith("KLIIEG_COLOUR "):
            return json.loads(line.split(" ", 1)[1])
    raise RuntimeError("no KLIIEG_COLOUR block; stderr: " + (p.stderr or "")[-400:])


def probe_session(bridge) -> dict:
    """Read colour state from a live session through the bridge."""
    r = bridge.eval(code="import json", expr="None")
    if not r.get("ok"):
        raise RuntimeError(r.get("error"))
    code = PROBE.replace('print("KLIIEG_COLOUR " + json.dumps(manifest))',
                         "RESULT = manifest")
    r = bridge.eval(code=code, expr="__import__('json').dumps(RESULT, sort_keys=True)")
    if not r.get("ok"):
        raise RuntimeError(r.get("error"))
    return json.loads(r["result"].strip("'"))


def stamp(manifest: dict) -> dict:
    m = dict(manifest)
    cfg = find_ocio_config()
    m["ocio_config"] = cfg
    m["ocio_config_sha256"] = sha256_of(cfg) if cfg else None
    return m


def write(path_dir: str, manifest: dict) -> str:
    os.makedirs(path_dir, exist_ok=True)
    p = os.path.join(path_dir, MANIFEST)
    with open(p, "w") as f:
        json.dump(stamp(manifest), f, indent=1, sort_keys=True)
    return p


def read(path_dir: str) -> dict | None:
    p = os.path.join(path_dir, MANIFEST)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def compare(expected: dict, actual: dict) -> list[dict]:
    """Field-level diffs. A changed view transform is a different film, not a detail."""
    diffs = []
    for k in sorted(set(expected) | set(actual)):
        if k in ("ocio_config", "ocio_config_sha256", "ocio_resource_path"):
            continue
        a, b = expected.get(k), actual.get(k)
        if a != b:
            diffs.append({"field": k, "expected": a, "actual": b})
    return diffs


def ffprobe_tags(path: str) -> dict:
    out = core.run_child(["ffprobe", "-v", "error", "-print_format", "json",
                          "-show_streams", "-show_format", path])
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return {}
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "color_space": v.get("color_space"),
        "color_primaries": v.get("color_primaries"),
        "color_transfer": v.get("color_transfer"),
        "color_range": v.get("color_range"),
    }


def tags_ok(path: str) -> tuple[bool, dict]:
    t = ffprobe_tags(path)
    ok = (t.get("color_space") == "bt709" and t.get("color_primaries") == "bt709"
          and t.get("color_transfer") == "bt709")
    return ok, t
