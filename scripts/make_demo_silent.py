"""Klieg launch cut: real PTY + frames + board. Captions. Synth bed. NO AI voice.

Pattern from your working demos:
  - hermes-portal: make_music.py ambient + real terminal clips + captions
  - rustbrain: synth premix (no voice in stems) + captions
  - xevrion_the1 launch recipe: real screen footage, short, 1080p, product first

    python3 scripts/make_music.py
    python3 scripts/make_demo_silent.py
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H, FPS = 1920, 1080, 30
BG = (8, 10, 13)
PANEL = (14, 17, 22)
INK = (232, 238, 246)
DIM = (150, 160, 175)
ACC = (96, 165, 250)
WARN = (251, 146, 60)
OK = (86, 214, 146)

CAST = os.path.join(REPO, "docs/media/cast.json")
BOARD = os.path.join(REPO, "docs/media/whiteboard.png")
MUSIC = os.path.join(REPO, "docs/media/music.wav")
OUT = os.path.join(REPO, "docs/media/klieg_demo.mp4")
STORY = os.path.join(REPO, "docs/media/storyboard.json")
WORK = "/tmp/klieg-demo-silent"
FRAMES = os.path.join(WORK, "vframes")
FILM = os.path.expanduser("~/projects/omnitrix-strobe/renders/frames")
MONO = "/usr/share/fonts/TTF/JetBrainsMonoNLNerdFontMono-Regular.ttf"
TAG = "/usr/share/fonts/OTF/SpaceGrotesk-Regular.otf"

# xevrion-ish: short, product first, captions carry the story (no TTS)
# total target ~48s
BEATS = [
    # cold open: stale verify already on screen
    dict(name="hook", start=0.0, end=6.0, mode="cast", cast_t=5.5,
         title="A render finished.",
         sub="Exit 0. Frames on disk. Wrong job."),
    dict(name="stale", start=6.0, end=14.0, mode="cast", cast_t=7.5,
         title="klieg jobs verify",
         sub="stale: 1   artefacts: []   refused"),
    dict(name="probe", start=14.0, end=22.0, mode="cast", cast_t=1.5,
         title="probe  ->  plan",
         sub="288 frames. Predicted duration. No GPU yet."),
    dict(name="render", start=22.0, end=30.0, mode="cast", cast_t=14.0,
         title="render detaches",
         sub="Shell can die. Job keeps log + exit + status."),
    dict(name="verify", start=30.0, end=36.0, mode="cast", cast_t=17.0,
         title="verify does not trust exit codes",
         sub="exists  AND  mtime >= start  AND  count"),
    dict(name="result", start=36.0, end=42.0, mode="sheet",
         title="frames this job wrote",
         sub="read off disk"),
    dict(name="board", start=42.0, end=48.0, mode="board",
         title="how it works",
         sub="agent -> gate -> adapter -> job -> verify"),
    dict(name="end", start=48.0, end=52.0, mode="end",
         title="Klieg",
         sub="github.com/LangerSword/hermes-klieg"),
]


def font(p, s):
    try:
        return ImageFont.truetype(p, s)
    except OSError:
        return ImageFont.load_default()


def counts():
    tools = len(re.findall(r"^\s+- klieg_", open(os.path.join(REPO, "plugin.yaml")).read(), re.M))
    n = 0
    for root, _, files in os.walk(os.path.join(REPO, "tests")):
        for fn in files:
            if fn.startswith("test_") and fn.endswith(".py"):
                n += len(re.findall(r"^\s*def test_", open(os.path.join(root, fn)).read(), re.M))
    return tools, n


def load_cast():
    data = json.load(open(CAST))
    return data["events"], float(data["duration"])


def cast_until(events, t):
    return "".join(x for et, x in events if et <= t)


def film_items(n=8):
    out = []
    for f in (0, 24, 54, 90, 132, 168, 216, 280):
        p = os.path.join(FILM, "%04d.png" % f)
        if os.path.exists(p):
            out.append((f, p))
    return out[:n]


def draw_caption(d, title, sub):
    # big left caption strip - xevrion/launch style, not tiny lower-third
    d.rectangle([0, 0, 520, H], fill=(6, 8, 11))
    d.rectangle([520, 0, 524, H], fill=ACC)
    # wrap title
    y = 120
    words = title.split()
    line = ""
    lines = []
    for w in words:
        trial = (line + " " + w).strip()
        if d.textlength(trial, font=font(TAG, 48)) > 460:
            lines.append(line)
            line = w
        else:
            line = trial
    if line:
        lines.append(line)
    for ln in lines:
        d.text((36, y), ln, font=font(TAG, 48), fill=INK)
        y += 58
    y += 24
    for ln in _wrap(d, sub, font(MONO, 26), 460):
        d.text((36, y), ln, font=font(MONO, 26), fill=DIM)
        y += 34


def _wrap(d, text, fnt, max_w):
    words = text.split()
    line, out = "", []
    for w in words:
        trial = (line + " " + w).strip()
        if d.textlength(trial, font=fnt) > max_w:
            if line:
                out.append(line)
            line = w
        else:
            line = trial
    if line:
        out.append(line)
    return out


def draw_term(img, lines):
    d = ImageDraw.Draw(img)
    # terminal on the right of caption strip
    x0 = 540
    d.rectangle([x0, 40, W - 40, H - 40], fill=PANEL, outline=(40, 48, 58), width=2)
    d.rectangle([x0, 40, W - 40, 88], fill=(20, 24, 30))
    for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        d.ellipse([x0 + 20 + i * 26, 54, x0 + 36 + i * 26, 70], fill=c)
    d.text((x0 + 110, 54), "klieg - recorded PTY", font=font(MONO, 20), fill=DIM)
    y = 110
    fm = font(MONO, 20)
    for raw in lines[-26:]:
        line = re.sub(r"\x1b\[[0-9;]*m", "", raw).replace("\t", "  ")
        line = line.replace(os.path.expanduser("~"), "~")
        line = re.sub(r"/home/[^/\s]+", "~", line)
        if len(line) > 78:
            line = line[:77] + "..."
        col = INK
        if line.startswith("$") or "klieg" in line[:12]:
            col = ACC
        if "stale" in line or '"ok": false' in line:
            col = WARN
        if '"ok": true' in line:
            col = OK
        d.text((x0 + 24, y), line, font=fm, fill=col)
        y += 28
        if y > H - 60:
            break


def draw_sheet(img, items, t):
    d = ImageDraw.Draw(img)
    d.rectangle([540, 40, W - 40, H - 40], fill=(12, 14, 18))
    cols = 4
    cw, ch = 300, 340
    x0, y0 = 580, 100
    for i, (num, path) in enumerate(items):
        cx = x0 + (i % cols) * (cw + 16)
        cy = y0 + (i // cols) * (ch + 16)
        if t < i * 0.12:
            continue
        try:
            im = Image.open(path).convert("RGBA")
            im.thumbnail((cw - 12, ch - 36))
            panel = Image.new("RGB", (cw, ch), (18, 22, 28))
            panel.paste(im, ((cw - im.width) // 2, 28), im)
            img.paste(panel, (cx, cy))
        except OSError:
            continue
        d.rectangle([cx, cy, cx + cw, cy + ch], outline=(48, 56, 68))
        d.text((cx + 10, cy + 6), "f%04d" % num, font=font(MONO, 16), fill=ACC)


def draw_board(img, t):
    board = Image.open(BOARD).convert("RGB")
    # right pane
    box_w, box_h = W - 580, H - 80
    scale = max(box_w / board.width, box_h / board.height) * (1.0 + 0.03 * min(1.0, t / 6))
    nw, nh = int(board.width * scale), int(board.height * scale)
    board = board.resize((nw, nh), Image.Resampling.LANCZOS)
    ox = max(0, (nw - box_w) // 2)
    oy = max(0, (nh - box_h) // 2)
    crop = board.crop((ox, oy, ox + box_w, oy + box_h))
    img.paste(crop, (540, 40))


def draw_end(img, tools, tests):
    d = ImageDraw.Draw(img)
    d.rectangle([540, 40, W - 40, H - 40], fill=(10, 12, 16))
    d.text((600, 320), "Klieg", font=font(TAG, 96), fill=INK)
    d.text((604, 440), "DCC bridge for Hermes", font=font(TAG, 36), fill=DIM)
    d.text((604, 520), "verify by mtime, not hope", font=font(MONO, 28), fill=ACC)
    d.text((604, 620), "github.com/LangerSword/hermes-klieg", font=font(MONO, 26), fill=INK)
    d.text((604, 680), f"{tools} tools  |  {tests} tests  |  real PTY", font=font(MONO, 22), fill=DIM)


def main() -> int:
    os.makedirs(FRAMES, exist_ok=True)
    for n in os.listdir(FRAMES):
        os.remove(os.path.join(FRAMES, n))

    if not os.path.exists(MUSIC):
        subprocess.run([sys.executable, os.path.join(REPO, "scripts/make_music.py")], check=True)

    events, cast_dur = load_cast()
    tools, tests = counts()
    items = film_items()
    total = BEATS[-1]["end"]
    story = {
        "fps": FPS,
        "duration": total,
        "beats": [
            {"name": b["name"], "start": b["start"], "end": b["end"],
             "caption": f"{b['title']} | {b['sub']}", "claim": None}
            for b in BEATS
        ],
        "numbers": {"tools": tools, "tests": tests},
        "audio": "docs/media/music.wav synthesized in-repo (make_music.py); no VO",
    }
    json.dump(story, open(STORY, "w"), indent=1)
    print("total", total, "s tools/tests", tools, tests)

    n_frames = int(total * FPS)
    for i in range(n_frames):
        t = i / FPS
        beat = BEATS[-1]
        for b in BEATS:
            if b["start"] <= t < b["end"]:
                beat = b
                break
        local = t - beat["start"]
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        draw_caption(d, beat["title"], beat["sub"])

        if beat["mode"] == "cast":
            ct = min(float(beat["cast_t"]) + local * 0.7, cast_dur - 0.05)
            lines = cast_until(events, ct).splitlines()
            draw_term(img, lines)
        elif beat["mode"] == "sheet":
            draw_sheet(img, items, local)
        elif beat["mode"] == "board":
            draw_board(img, local)
        else:
            draw_end(img, tools, tests)

        d2 = ImageDraw.Draw(img)
        d2.text((W - 140, H - 48), "klieg", font=font(MONO, 20), fill=ACC)
        img.save(os.path.join(FRAMES, "%04d.png" % i), compress_level=1)
        if i % 120 == 0:
            print(f"  {i}/{n_frames}")

    silent = os.path.join(WORK, "silent.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", str(FPS), "-i", os.path.join(FRAMES, "%04d.png"),
        "-vf", "fps=30,format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart",
        silent,
    ], check=True)

    # music bed only - atrim + -t lock (never bare apad forever)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", silent, "-i", MUSIC,
        "-filter_complex",
        f"[1:a]atrim=0:{total:.3f},afade=t=in:st=0:d=0.8,"
        f"afade=t=out:st={max(0,total-2.5):.3f}:d=2.5,"
        f"volume=0.45,loudnorm=I=-18:TP=-2.0:LRA=11[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{total:.3f}",
        "-movflags", "+faststart",
        OUT,
    ], check=True)
    print("demo", OUT, os.path.getsize(OUT), "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
