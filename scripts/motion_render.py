"""Render a motion scene (HTML+GSAP) to MP4/GIF, deterministically frame by frame.

    <python-with-playwright> scripts/motion_render.py SCENE.html OUT \
        --fps 30 --duration 6 --width 1920 --height 1080 --format mp4 [--music bed.wav]
    <python> scripts/motion_render.py SCENE.html OUT.png --preview 2.5 --width 1920 --height 1080

Seeking the timeline and screenshotting each frame guarantees every frame is
fully painted (no screencast frame-drops), so motion is smooth. The scene must
expose window.__tl (klieg_motion's compiler does); raw HTML may rely on
gsap.globalTimeline. Needs playwright + a chromium headless shell.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The plugin root, so the frame work dir can live in the plugin data dir.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:  # loaded as a Hermes plugin package
    from .. import klieg_core as core
except ImportError:  # run as a script (the normal path) or standalone
    import klieg_core as core


def _browser(p):
    return p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])


def _seek(page, t):
    page.evaluate(
        "(t) => { const tl = window.__tl || (window.gsap && gsap.globalTimeline);"
        " if (tl) { tl.pause(); tl.seek(t, false); } }", t)


def render_frames(html: Path, frames: Path, fps: int, duration: float, w: int, h: int):
    from playwright.sync_api import sync_playwright
    # `frames` is a fresh, exclusively-owned temp dir (see main): nothing here
    # may delete pre-existing files, because a predictable work-dir name once
    # emptied a user folder that happened to match it.
    frames.mkdir(parents=True, exist_ok=True)
    n = int(round(duration * fps))
    with sync_playwright() as p:
        b = _browser(p)
        page = b.new_page(viewport={"width": w, "height": h})
        page.goto(html.as_uri(), wait_until="load")
        page.wait_for_timeout(600)
        for i in range(n):
            _seek(page, i / fps)
            page.screenshot(path=str(frames / f"{i:04d}.png"))
            if i % 150 == 0:
                print(f"  {i}/{n}", flush=True)
        b.close()
    return n


def preview(html: Path, out: Path, t: float, w: int, h: int):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = _browser(p)
        page = b.new_page(viewport={"width": w, "height": h})
        page.goto(html.as_uri(), wait_until="load")
        page.wait_for_timeout(600)
        _seek(page, t)
        page.screenshot(path=str(out))
        b.close()


def to_mp4(frames: Path, out: Path, fps: int, music: str | None, duration: float):
    silent = out.with_suffix(".silent.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
        "-i", str(frames / "%04d.png"),
        "-vf", "fps=%d,scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p" % fps,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-r", str(fps), "-movflags", "+faststart", str(silent),
    ], check=True)
    if music:
        fade = max(0.0, duration - 2.0)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", music,
            "-filter_complex",
            f"[1:a]atrim=0:{duration:.3f},afade=t=in:st=0:d=0.6,"
            f"afade=t=out:st={fade:.3f}:d=2.0,volume=0.5,loudnorm=I=-18:TP=-2.0:LRA=11[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
            "-b:a", "192k", "-ar", "48000", "-t", f"{duration:.3f}",
            "-movflags", "+faststart", str(out),
        ], check=True)
        silent.unlink(missing_ok=True)
    else:
        silent.replace(out)


def to_gif(frames: Path, out: Path, fps: int, w: int):
    palette = out.with_suffix(".palette.png")
    vf = f"fps={fps},scale={w}:-1:flags=lanczos"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                    "-i", str(frames / "%04d.png"),
                    "-vf", f"{vf},palettegen=stats_mode=diff", str(palette)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                    "-i", str(frames / "%04d.png"), "-i", str(palette),
                    "-lavfi", f"{vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4",
                    str(out)], check=True)
    palette.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("out")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--duration", type=float, default=6.0)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--format", choices=["mp4", "gif"], default="mp4")
    ap.add_argument("--music", default=None)
    ap.add_argument("--preview", type=float, default=None)
    a = ap.parse_args()

    html = Path(a.html).resolve()
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("ERROR: playwright not installed in this interpreter. "
              "pip install playwright && playwright install chromium-headless-shell", flush=True)
        return 2

    if a.preview is not None:
        preview(html, out, a.preview, a.width, a.height)
        print("preview", out, flush=True)
        return 0

    # A fresh unique dir under the plugin data dir, never a predictable name
    # next to the output: <out stem>_frames could be a user's own folder, and
    # the old code emptied it before and after every render.
    work = Path(tempfile.mkdtemp(prefix="motion-frames-", dir=core.data_dir()))
    try:
        n = render_frames(html, work, a.fps, a.duration, a.width, a.height)
        print("frames done", n, flush=True)
        if a.format == "gif":
            to_gif(work, out, a.fps, a.width)
        else:
            to_mp4(work, out, a.fps, a.music, a.duration)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("motion", out, out.stat().st_size, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())