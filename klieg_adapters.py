"""Adapters: one interface, one file per host.

Every DCC has the same shape of problem - a binary that wants a scene file, a
Python that is not the system Python, and a render that takes long enough to
outlive the caller. The adapter only has to answer three questions:

    detect()          what is installed, and which version
    run_argv(...)     how to run a python script inside it, headless
    render_argv(...)  how to render a frame range

Live bridging (a socket into an already-open UI session) is deliberately out of
scope for 0.1: it is per-host, needs an addon inside the app, and a crashed
socket is worse than a batch job. The interface leaves room for it as
`session()` returning None today.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess

# Blender resolves its stdlib from the first python3.X on PATH. A pyenv/uv/conda
# prefix ahead of /usr/bin makes it adopt that home and lose `math`, which reads
# as a broken install. Every launch goes through this env.
SAFE_ENV = {"PATH": "/usr/bin:/bin:/usr/local/bin"}


class Adapter:
    name = ""
    label = ""
    binaries: tuple[str, ...] = ()
    fallback_globs: tuple[str, ...] = ()

    # ---- discovery
    def find_binary(self) -> str | None:
        for b in self.binaries:
            p = shutil.which(b)
            if p:
                return p
        for pattern in self.fallback_globs:
            hits = sorted(glob.glob(pattern), reverse=True)
            if hits:
                return hits[0]
        return None

    def detect(self) -> dict:
        path = self.find_binary()
        if not path:
            return {"dcc": self.name, "found": False}
        return {"dcc": self.name, "found": True, "path": path,
                "version": self.version(path)}

    def version(self, path: str) -> str:
        try:
            out = subprocess.run([path, "--version"], capture_output=True, text=True,
                                 timeout=20, env={**os.environ, **SAFE_ENV})
            return (out.stdout or out.stderr).splitlines()[0].strip()
        except Exception as e:                      # noqa: BLE001 - report, never raise
            return f"unknown ({type(e).__name__})"

    # ---- execution
    def run_argv(self, script: str, blend: str | None = None, args: list[str] | None = None) -> list[str]:
        raise NotImplementedError

    def render_argv(self, frames: list[int], outdir: str, samples: int,
                    pct: int, blend: str, tag: str = "") -> list[str]:
        raise NotImplementedError

    def session(self) -> None:
        """Live bridge hook. Not implemented in 0.1 - batch is the reliable path."""
        return None


class Blender(Adapter):
    name = "blender"
    label = "Blender"
    binaries = ("blender",)
    fallback_globs = ("/opt/blender*/blender", "/snap/bin/blender")

    def run_argv(self, script, blend=None, args=None):
        argv = [self.find_binary() or "blender", "-b", "--factory-startup"]
        if blend:
            argv.append(blend)
        argv += ["-P", script]
        if args:
            argv += ["--", *args]
        return argv

    def render_argv(self, frames, outdir, samples, pct, blend, tag=""):
        # a generated script keeps the CLI surface tiny and the behaviour explicit
        script = os.path.join(os.path.dirname(outdir), "_klieg_render.py")
        os.makedirs(os.path.dirname(outdir), exist_ok=True)
        with open(script, "w") as f:
            f.write(RENDER_SCRIPT.format(
                frames=",".join(str(f) for f in frames), outdir=outdir,
                samples=samples, pct=pct))
        return self.run_argv(script, blend=blend)


RENDER_SCRIPT = '''\
import bpy, os, json, sys, time
FRAMES = [int(x) for x in "{frames}".split(",") if x]
OUT = "{outdir}"
sc = bpy.context.scene
sc.cycles.samples = {samples}
sc.cycles.use_adaptive_sampling = True
sc.cycles.adaptive_threshold = 0.03
sc.cycles.use_denoising = True
sc.render.resolution_percentage = {pct}
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGBA"
sc.render.image_settings.color_depth = "16"
os.makedirs(OUT, exist_ok=True)
times = {{}}
for f in FRAMES:
    sc.frame_set(f)
    sc.render.filepath = os.path.join(OUT, "%04d.png" % f)
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    times[f] = round(time.time() - t0, 2)
    print("KLIIEG_RENDERED", f, times[f], flush=True)
print("KLIIEG_RENDER_JSON", json.dumps(times), flush=True)
'''


class Houdini(Adapter):
    """hython, batch. Live hrpyc is a later adapter version."""
    name = "houdini"
    label = "Houdini"
    binaries = ("hython",)
    fallback_globs = ("/opt/hfs*/bin/hython",)

    def run_argv(self, script, blend=None, args=None):
        return [self.find_binary() or "hython", script, *(args or [])]


class Nuke(Adapter):
    name = "nuke"
    label = "Nuke"
    binaries = ("nuke",)
    fallback_globs = ("/usr/local/Nuke*/Nuke*",)

    def run_argv(self, script, blend=None, args=None):
        return [self.find_binary() or "nuke", "-t", script, *(args or [])]

    def version(self, path):
        try:
            out = subprocess.run([path, "-version"], capture_output=True, text=True,
                                 timeout=20, env={**os.environ, **SAFE_ENV})
            return (out.stdout or out.stderr).splitlines()[0].strip()
        except Exception:
            return "unknown"


class Cinema4D(Adapter):
    name = "c4d"
    label = "Cinema 4D"
    binaries = ("c4d", "Cinema 4D")
    fallback_globs = ("/opt/cinema4d/*",)

    def version(self, path):
        return "see -help (C4D reports version at launch)"


class AfterEffects(Adapter):
    """After Effects has no CLI python; it is driven through ExtendScript or UXP.

    Kept in the registry so `klieg_probe` reports it as present-but-unsupported
    rather than silently missing. The adapter returns None from run_argv.
    """
    name = "ae"
    label = "After Effects"
    binaries = ("afterfx", "AfterFX.exe")
    fallback_globs = ("/opt/Adobe/After Effects*",)

    def run_argv(self, script, blend=None, args=None):
        return None

    def version(self, path):
        return "ExtendScript/UXP only - not driven in 0.1"


class Resolve(Adapter):
    name = "resolve"
    label = "DaVinci Resolve"
    binaries = ("resolve",)
    fallback_globs = ("/opt/resolve/bin/resolve",)

    def run_argv(self, script, blend=None, args=None):
        return None


ADAPTERS = {a.name: a for a in (Blender(), Houdini(), Nuke(), Cinema4D(), AfterEffects(), Resolve())}


def get(name: str) -> Adapter:
    if name not in ADAPTERS:
        raise KeyError(f"unknown dcc '{name}'; try one of {sorted(ADAPTERS)}")
    return ADAPTERS[name]


def probe_all() -> list[dict]:
    return [a.detect() for a in ADAPTERS.values()]
