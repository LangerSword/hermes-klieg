"""Render the cinematic explainer deterministically, frame by frame.

Seeking the GSAP timeline and screenshotting each frame guarantees every frame
is fully painted (no screencast frame-drops under the blur/grain load), so the
motion is smooth. Then ffmpeg the PNG sequence and mux the in-repo synth bed.
No TTS; captions live in the HTML.

    .venv/bin/python scripts/render_explainer.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
HTML = REPO / "docs/explainer/index.html"
OUT = REPO / "docs/media/klieg_demo.mp4"
MUSIC = REPO / "docs/media/music.wav"
WORK = Path("/tmp/klieg-anim")
FRAMES = WORK / "vframes"
TOTAL = 50.0
FPS = 30
N = int(TOTAL * FPS)


def main() -> int:
    FRAMES.mkdir(parents=True, exist_ok=True)
    for f in FRAMES.iterdir():
        f.unlink()
    if not MUSIC.exists():
        subprocess.run([sys.executable, str(REPO / "scripts/make_music.py")], check=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(HTML.as_uri(), wait_until="load")
        page.wait_for_timeout(700)
        page.evaluate("() => { window.__tl.pause(); }")
        for i in range(N):
            t = i / FPS
            page.evaluate("(t) => { window.__tl.seek(t, false); }", t)
            page.screenshot(path=str(FRAMES / f"{i:04d}.png"))
            if i % 150 == 0:
                print(f"  {i}/{N}", flush=True)
        browser.close()
    print("frames done", N, flush=True)

    silent = WORK / "silent.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", str(FPS), "-i", str(FRAMES / "%04d.png"),
        "-vf", "fps=30,format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart",
        str(silent),
    ], check=True)

    fade = max(0.0, TOTAL - 2.4)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(silent), "-i", str(MUSIC),
        "-filter_complex",
        f"[1:a]atrim=0:{TOTAL:.3f},afade=t=in:st=0:d=0.7,"
        f"afade=t=out:st={fade:.3f}:d=2.2,volume=0.5,loudnorm=I=-18:TP=-2.0:LRA=11[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{TOTAL:.3f}", "-movflags", "+faststart",
        str(OUT),
    ], check=True)
    print("demo", OUT, OUT.stat().st_size, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())