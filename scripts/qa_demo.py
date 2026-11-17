"""QA the rendered demo, not stills. Prints PASS/FAIL with measured values.

    <venv>/python scripts/qa_demo.py

Checks: container facts, first-frame luma, beat coverage, caption dwell, banned glyphs,
output-path leaks, and loudness of the actual file.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(REPO, "docs/media/klieg_demo.mp4")
STORY = os.path.join(REPO, "docs/media/storyboard.json")

results = []


def check(name, ok, detail):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:32s} {detail}")


def ffprobe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                          "-show_format", "-show_streams", path],
                         capture_output=True, text=True)
    return json.loads(out.stdout or "{}")


def main() -> int:
    if not os.path.exists(DEMO):
        print("no demo at", DEMO)
        return 1

    info = ffprobe(DEMO)
    fmt = info.get("format", {})
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {})
    dur = float(fmt.get("duration") or 0)
    size = int(fmt.get("size") or 0)
    fps = v.get("avg_frame_rate", "0/1")
    num, den = (int(x) for x in fps.split("/"))
    fps_val = num / den if den else 0

    check("duration 45-100s", 45 <= dur <= 100, f"{dur:.2f}s")
    check("size > 400 KB", size > 400_000, f"{size} bytes")
    check("video codec h264", v.get("codec_name") == "h264", str(v.get("codec_name")))
    check("resolution 1920x1080", (v.get("width"), v.get("height")) == (1920, 1080),
          f"{v.get('width')}x{v.get('height')}")
    check("frame rate ~30", 29.5 <= fps_val <= 30.5, f"{fps_val:.2f}")
    check("audio track present", bool(a), f"{a.get('codec_name')} {a.get('sample_rate')} Hz")

    # first frame must not be black
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "f0.png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", DEMO,
                        "-vframes", "1", p], check=False)
        if os.path.exists(p):
            luma = float(np.asarray(Image.open(p).convert("L")).mean())
            check("first frame not black", luma > 8, f"mean luma {luma:.1f}")
        else:
            check("first frame not black", False, "could not extract")

    story = json.load(open(STORY))
    beats = story["beats"]
    cat = float(story["duration"])
    check("beats sum to duration", abs(sum(b["end"] - b["start"] for b in beats) - cat) < 0.2,
          f"{sum(b['end'] - b['start'] for b in beats):.2f}s vs {cat:.2f}s")

    for b in beats:
        if b["caption"]:
            dwell = b["end"] - b["start"]
            check(f"dwell {b['name']}", dwell >= 2.0, f"{dwell:.1f}s")

    text = " ".join(b["caption"] for b in beats)
    banned = [c for c in ("—", "–", "·") if c in text]
    check("no em/en dash, no middot", not banned, f"found {banned}" if banned else "clean")
    leak = re.search(r"lakeshaya|/home/|sk-[A-Za-z0-9]", text)
    check("no path or handle leaks", leak is None, leak.group(0) if leak else "clean")

    # loudness of the file
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", DEMO,
                        "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    tail = r.stderr[-2500:]
    m = re.search(r"I:\s*(-?\d+\.\d+) LUFS", tail)
    tp = re.search(r"Peak:\s*(-?\d+\.\d+) dBFS", tail)
    if m:
        lufs = float(m.group(1))
        check("integrated loudness -20..-10", -20 <= lufs <= -10, f"{lufs} LUFS")
    else:
        check("integrated loudness -20..-10", False, "not measured")
    if tp:
        check("true peak under -1.0 dBFS", float(tp.group(1)) <= -1.0, f"{tp.group(1)} dBFS")

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED:", ", ".join(failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
