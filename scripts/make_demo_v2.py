"""Klieg demo, second cut: a recorded session, the frames it produced, the diagram.

    <venv>/python scripts/make_demo_v2.py

Sources, all real:
  docs/media/cast.json      timestamped PTY capture of the actual CLI
  renders/frames/*.png      frames written by the job in that capture (and the film
                            those frames belong to)
  docs/media/whiteboard.png the architecture diagram
  plugin.yaml + tests       the tool and test counts printed on the end card

Writes docs/media/klieg_demo.mp4 and docs/media/storyboard.json.
"""

import json
import math
import os
import re
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import klieg_core as core
import klieg_tools as tools

W, H, FPS = 1920, 1080, 30
BG = (8, 10, 13)
PANEL = (14, 17, 22)
INK = (232, 238, 246)
DIM = (142, 155, 172)
ACC = (96, 165, 250)
WARN = (251, 146, 60)
OK = (86, 214, 146)
FRAMES = "/tmp/klieg-demo2/frames"
OUT = os.path.join(REPO, "docs/media/klieg_demo.mp4")
CAST = os.path.join(REPO, "docs/media/cast.json")
BOARD = os.path.join(REPO, "docs/media/whiteboard.png")
FILM = os.path.expanduser("~/projects/omnitrix-strobe/renders/frames")
MONO = "/usr/share/fonts/TTF/JetBrainsMonoNLNerdFontMono-Regular.ttf"
TAG = "/usr/share/fonts/OTF/SpaceGrotesk-Regular.otf"


def font(p, s):
    try:
        return ImageFont.truetype(p, s)
    except OSError:
        return ImageFont.load_default()


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def counts():
    """Read the claims from the product, never type them."""
    tools_n = len(re.findall(r"^\s+- klieg_", open(os.path.join(REPO, "plugin.yaml")).read(), re.M))
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                       cwd=REPO, capture_output=True, text=True)
    m = re.search(r"Ran (\d+) tests", r.stderr + r.stdout)
    return {"tools": tools_n, "tests": int(m.group(1)) if m else 0}


# ------------------------------------------------------------------ cast replay
def load_cast():
    data = json.load(open(CAST))
    return data["events"], float(data["duration"])


def cast_text_until(events, t):
    return "".join(text for et, text in events if et <= t)


# ------------------------------------------------------------------ frames
def film_frames(n=9):
    out = []
    for f in (0, 12, 54, 90, 132, 168, 216, 230, 280):
        p = os.path.join(FILM, "%04d.png" % f)
        if os.path.exists(p):
            out.append((f, p))
    return out[:n]


def draw_terminal(d, text_lines, t):
    # window chrome
    d.rectangle([0, 0, W, 54], fill=PANEL)
    for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        d.ellipse([26 + i * 26, 18, 44 + i * 26, 36], fill=c)
    d.text((130, 16), "klieg — recorded session", font=font(MONO, 20), fill=DIM)
    d.text((W - 210, 16), "1.0x", font=font(MONO, 20), fill=DIM)

    y = 92
    fm = font(MONO, 21)
    for raw in text_lines:
        line = re.sub(r"\x1b\[[0-9;]*m", "", raw).replace("\t", "    ")
        line = line.replace(os.path.expanduser("~"), "~")      # no usernames in frame
        if len(line) > 108:
            line = line[:107] + "…"
        colour = INK
        if line.startswith("klieg $"):
            colour = ACC
        elif '"ok": false' in line or '"stale": 1' in line:
            colour = WARN
        elif '"ok": true' in line:
            colour = OK
        d.text((44, y), line, font=fm, fill=colour)
        y += 30
        if y > H - 60:
            break


def draw_title(t, alpha):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # punch: one sentence a producer feels in the gut
    d.text((120, 360), "Klieg", font=font(TAG, 150), fill=INK)
    d.text((126, 530), "Hermes can write the render script.", font=font(TAG, 42), fill=DIM)
    d.text((126, 590), "Klieg makes sure the frames actually happened.", font=font(TAG, 42), fill=INK)
    d.text((128, 680), "a DCC bridge  ·  verify by mtime, not by hope", font=font(MONO, 26), fill=ACC)
    return img


def draw_sheet(t, items, alpha):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((80, 60), "frames written by the job above", font=font(TAG, 40), fill=INK)
    d.text((82, 116), "read straight off disk, frame numbers burned in", font=font(MONO, 20), fill=DIM)

    cols, rows = 5, 2
    cw, ch = 330, 380
    x0, y0 = 80, 190
    for i, (num, path) in enumerate(items):
        cx = x0 + (i % cols) * (cw + 22)
        cy = y0 + (i // cols) * (ch + 26)
        appear = ease((t - i * 0.16) / 0.9)
        if appear <= 0:
            continue
        try:
            im = Image.open(path).convert("RGBA")
            im.thumbnail((cw, ch))
            panel = Image.new("RGB", (cw, ch), (16, 19, 24))
            panel.paste(im, ((cw - im.width) // 2, (ch - im.height) // 2), im)
            panel = panel.resize((int(cw * (0.86 + 0.14 * appear)), int(ch * (0.86 + 0.14 * appear))))
            img.paste(panel, (cx, cy + int((ch - panel.height) / 2)))
        except OSError:
            continue
        d.rectangle([cx, cy, cx + cw, cy + ch], outline=(44, 52, 64))
        d.text((cx + 10, cy + 8), "f%03d" % num, font=font(MONO, 18), fill=ACC)
    return img


def draw_board(t, callouts, alpha):
    board = Image.open(BOARD).convert("RGB")
    scale = 1.03 + 0.05 * (t / 12.0)
    w, h = int(board.width * scale), int(board.height * scale)
    board = board.resize((w, h), Image.LANCZOS)
    ox = (w - W) // 2 + int(30 * math.sin(t / 6))
    oy = (h - H) // 2
    img = board.crop((ox, oy, ox + W, oy + H)) if w >= W and h >= H else board.resize((W, H))
    d = ImageDraw.Draw(img, "RGBA")
    for i, (x, y, label, at) in enumerate(callouts):
        if t < at:
            continue
        a = int(220 * ease((t - at) / 0.5))
        d.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(96, 165, 250, a), width=3)
        d.text((x + 16, y - 12), label, font=font(MONO, 19), fill=(226, 232, 240, a))
    return img


def draw_end(t, nums, alpha):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((120, 380), "github.com/LangerSword/hermes-klieg", font=font(TAG, 54), fill=INK)
    d.text((122, 470), f"{nums['tools']} tools · 1 hook · {nums['tests']} tests", font=font(MONO, 28), fill=ACC)
    d.text((122, 530), "a job is done when its artefact is newer than the job started",
           font=font(MONO, 24), fill=DIM)
    return img


_VIG = None


def vignette(img):
    """Cached mask: building a 1920x1080 Gaussian blur per frame dominated the render."""
    global _VIG
    if _VIG is None:
        mask = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(mask)
        d.ellipse([-W * 0.25, -H * 0.35, W * 1.25, H * 1.35], fill=255)
        _VIG = mask.filter(ImageFilter.GaussianBlur(140))
    dark = Image.new("RGB", (W, H), (0, 0, 0))
    return Image.composite(img, dark, _VIG)


def grain(img, amount=6, seed=0):
    """Vectorised noise - a 9000-iteration pixel loop per frame was the bottleneck."""
    rng = np.random.default_rng(seed)
    arr = np.asarray(img).astype(np.int16)
    n = rng.integers(-amount, amount + 1, arr.shape[:2], dtype=np.int16)[..., None]
    return Image.fromarray(np.clip(arr + n, 0, 255).astype(np.uint8))


def main() -> int:
    events, cast_dur = load_cast()
    nums = counts()
    items = film_frames()
    print("cast", round(cast_dur, 1), "s | frames", len(items), "| tools/tests", nums)

    term_start = 2.0
    term_span = cast_dur + 1.0
    sheet_start = term_start + term_span
    board_start = sheet_start + 10.0
    end_start = board_start + 15.0   # longer dwell on the hand board
    total = end_start + 5.0

    beats = [
        dict(name="title", start=0.0, end=term_start,
             caption="", claim=None),
        dict(name="session", start=term_start, end=sheet_start,
             caption="a real recorded session: probe, a stale artefact refused, plan, render, verify",
             claim=None),
        dict(name="frames", start=sheet_start, end=board_start,
             caption="the frames that job wrote, read off disk", claim="frames written"),
        dict(name="board", start=board_start, end=end_start,
             caption="whiteboard: agent → gate → adapter → job dir → verify by mtime",
             claim=None),
        dict(name="end", start=end_start, end=total,
             caption="", claim=f"{nums['tools']} tools, {nums['tests']} tests"),
    ]
    json.dump({"fps": FPS, "duration": round(total, 2), "beats": beats, "numbers": nums},
              open(os.path.join(REPO, "docs/media/storyboard.json"), "w"), indent=1)

    os.makedirs(FRAMES, exist_ok=True)
    for n in os.listdir(FRAMES):
        os.remove(os.path.join(FRAMES, n))

    # positions on the 1920x1080 crop of the hand-drawn board (approx)
    callouts = [
        (280, 300, "1 agent calls a verb", 0.5),
        (700, 300, "2 human gate (klieg:*)", 2.0),
        (1120, 280, "3 adapter → argv", 3.5),
        (250, 620, "5 one GPU lock / queue", 5.0),
        (720, 620, "6 job dir survives the shell", 6.5),
        (1280, 620, "7 verify: mtime wins", 8.0),
    ]

    n_frames = int(total * FPS)
    print("rendering", n_frames, "frames...")
    for i in range(n_frames):
        t = i / FPS
        if t < term_start:
            img = draw_title(t, 1.0)
        elif t < sheet_start:
            img = Image.new("RGB", (W, H), BG)
            d = ImageDraw.Draw(img)
            draw_terminal(d, cast_text_until(events, t - term_start).splitlines(), t)
        elif t < board_start:
            img = draw_sheet(t - sheet_start, items, 1.0)
        elif t < end_start:
            img = draw_board(t - board_start, callouts, 1.0)
        else:
            img = draw_end(t - end_start, nums, 1.0)

        # beat label, bottom left
        d = ImageDraw.Draw(img)
        for b in beats:
            if b["start"] <= t < b["end"] and b["caption"]:
                a = int(200 * ease(min((t - b["start"]) / 0.5, (b["end"] - t) / 0.5)))
                d.text((72, H - 74), b["caption"], font=font(MONO, 21), fill=(*DIM[:3], a))
        d.text((W - 170, H - 74), "klieg", font=font(MONO, 21), fill=DIM)

        img = vignette(img)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=40, threshold=3))
        img.save(os.path.join(FRAMES, "%04d.png" % i), compress_level=1)

    print("muxing audio + encode...")
    audio = os.path.expanduser("~/projects/omnitrix-strobe/deliver/audio/mix.wav")
    silent = "/tmp/klieg-demo2/silent.mp4"
    # full HD, constant fps, dense keyframes — no mid-file seek traps later
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", str(FPS),
        "-i", os.path.join(FRAMES, "%04d.png"),
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
               "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x080a0d,"
               "fps=30,format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-movflags", "+faststart",
        silent,
    ], check=True)
    if os.path.exists(audio):
        # -t locks duration: apad alone would run forever on a long mix.wav
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", silent, "-i", audio,
            "-filter_complex",
            "[1:a]atrim=0:%.3f,volume=0.55,afade=t=in:st=0:d=0.6,"
            "afade=t=out:st=%.3f:d=2.0,apad=whole_dur=%.3f[a]"
            % (total, max(0.0, total - 2.0), total),
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-t", "%.3f" % total,
            "-color_primaries", "bt709", "-color_trc", "bt709",
            "-colorspace", "bt709", "-color_range", "tv",
            "-movflags", "+faststart",
            OUT,
        ], check=True)
    else:
        os.replace(silent, OUT)

    size = os.path.getsize(OUT)
    print("demo:", OUT, size, "bytes", round(total, 1), "s")
    return 0 if size else 1


if __name__ == "__main__":
    raise SystemExit(main())
