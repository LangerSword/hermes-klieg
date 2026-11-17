#!/usr/bin/env python3
"""Record the cinematic explainer (1920x1080) then mux in-repo synth bed.

No TTS. Captions live in the HTML.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HTML = REPO / "docs/explainer/index.html"
OUT = REPO / "docs/media/klieg_demo.mp4"
MUSIC = REPO / "docs/media/music.wav"
WORK = Path("/tmp/klieg-explainer")
TOTAL = 50.0

def main() -> int:
    WORK.mkdir(exist_ok=True)
    music_py = REPO / "scripts/make_music.py"
    if not MUSIC.exists():
        subprocess.run([sys.executable, str(music_py)], check=True)

    from playwright.sync_api import sync_playwright

    url = HTML.as_uri()
    raw = WORK / "raw.webm"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(WORK),
            record_video_size={"width": 1920, "height": 1080},
        )
        page = ctx.new_page()
        page.goto(url, wait_until="load")
        page.wait_for_timeout(int(TOTAL * 1000) + 800)
        vid = page.video
        ctx.close()
        src = Path(vid.path()) if vid else None
        browser.close()
        if not src or not src.exists():
            print("no video")
            return 1
        src.replace(raw)
        print("raw", raw, raw.stat().st_size)

    silent = WORK / "silent.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(raw),
        "-vf", "fps=30,scale=1920:1080:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-an", "-t", f"{TOTAL:.3f}",
        "-movflags", "+faststart",
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
        "-t", f"{TOTAL:.3f}",
        "-movflags", "+faststart",
        str(OUT),
    ], check=True)
    print("demo", OUT, OUT.stat().st_size)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
