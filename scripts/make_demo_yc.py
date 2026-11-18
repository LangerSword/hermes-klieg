"""YC-style Klieg product demo — original VO, real product, one workflow.

Structure (YC / product-demo practice):
  0–8s   cold open inside the product (stale verify fails)
  8–48s  one workflow: probe → plan → render → verify
  48–58s result on disk (frames the job wrote)
  58–68s how verify works (hand whiteboard, short)
  68–75s end card

Audio: Piper TTS written for this cut only. No music bed from another project.

    python3 scripts/make_demo_yc.py
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import resolve_input
sys.path.insert(0, REPO)

W, H, FPS = 1920, 1080, 30
BG = (8, 10, 13)
PANEL = (14, 17, 22)
INK = (232, 238, 246)
DIM = (142, 155, 172)
ACC = (96, 165, 250)
WARN = (251, 146, 60)
OK = (86, 214, 146)

CAST = os.path.join(REPO, "docs/media/cast.json")
BOARD = os.path.join(REPO, "docs/media/whiteboard.png")
OUT = os.path.join(REPO, "docs/media/klieg_demo.mp4")
STORY = os.path.join(REPO, "docs/media/storyboard.json")
WORK = "/tmp/klieg-demo-yc"
FRAMES = os.path.join(WORK, "frames")
VO_DIR = os.path.join(WORK, "vo")
FILM = resolve_input("film")

MONO = "/usr/share/fonts/TTF/JetBrainsMonoNLNerdFontMono-Regular.ttf"
TAG = "/usr/share/fonts/OTF/SpaceGrotesk-Regular.otf"
VOICE = "/home/lakshaya/projects/ash/demo/video/voices/en_GB-alan-medium.onnx"
PY = sys.executable

# YC script: problem → one workflow → result. Plain words. ~140 wpm.
# Spoken lines drive duration; picture holds under them.
SCRIPT = [
    # cold open — already in product
    {
        "id": "open",
        "mode": "cast",
        "cast_t0": 4.0,  # start near stale verify
        "vo": (
            "Agents can write a Blender render script. "
            "They cannot tell if the frames on disk are from this job, or the last one."
        ),
        "caption": "the problem: a finished render that lied",
    },
    {
        "id": "stale",
        "mode": "cast",
        "cast_t0": 5.5,
        "vo": (
            "Klieg is a DCC bridge for Hermes. "
            "Watch verify catch a stale job: exit code zero, artefacts empty, stale count one."
        ),
        "caption": "klieg jobs verify - stale artefact refused",
    },
    {
        "id": "probe",
        "mode": "cast",
        "cast_t0": 0.0,
        "vo": (
            "Same session. Probe what is installed. Plan the pass without touching the GPU. "
            "Two hundred eighty eight frames, predicted duration from this machine's history."
        ),
        "caption": "probe hosts | plan without running",
    },
    {
        "id": "render",
        "mode": "cast",
        "cast_t0": 12.0,
        "vo": (
            "Render detaches. The shell can die. The job keeps its own log, exit file, and status. "
            "When it finishes, verify does not trust the exit code alone."
        ),
        "caption": "detached render | job dir survives the shell",
    },
    {
        "id": "verify_ok",
        "mode": "cast",
        "cast_t0": 16.0,
        "vo": (
            "Verify asks three questions. Does the file exist. "
            "Is its mtime newer than the job start. Did we get every frame we promised."
        ),
        "caption": "verify: mtime and count, not hope",
    },
    {
        "id": "result",
        "mode": "sheet",
        "vo": (
            "These are the frames that job wrote, read straight off disk. "
            "A count without a fresh mtime would still fail."
        ),
        "caption": "result: frames on disk from this job",
    },
    {
        "id": "board",
        "mode": "board",
        "vo": (
            "Agent calls a verb. Approval gate. Adapter builds argv. "
            "One GPU lock. Job directory. Verify is the only claim that matters."
        ),
        "caption": "how it works",
    },
    {
        "id": "end",
        "mode": "end",
        "vo": (
            "Klieg. A DCC bridge for Hermes. "
            "The render that cannot lie about finishing. "
            "github.com slash LangerSword slash hermes-klieg."
        ),
        "caption": "",
    },
]


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def counts():
    tools_n = len(re.findall(r"^\s+- klieg_", open(os.path.join(REPO, "plugin.yaml")).read(), re.M))
    r = subprocess.run(
        [PY, "-m", "unittest", "discover", "-s", "tests"],
        cwd=REPO, capture_output=True, text=True,
    )
    m = re.search(r"Ran (\d+) tests", r.stderr + r.stdout)
    # if suite errors, still report Ran N if present; else count test_*.py methods
    tests_n = int(m.group(1)) if m else 0
    if tests_n == 0 or r.returncode != 0:
        # fallback: count test_ functions without running broken imports as success claim
        n = 0
        for root, _, files in os.walk(os.path.join(REPO, "tests")):
            for fn in files:
                if fn.startswith("test_") and fn.endswith(".py"):
                    txt = open(os.path.join(root, fn)).read()
                    n += len(re.findall(r"^\s*def test_", txt, re.M))
        tests_n = n
    return {"tools": tools_n, "tests": tests_n, "tests_ok": r.returncode == 0}


def wav_duration(path: str) -> float:
    with wave.open(path) as w:
        return w.getnframes() / float(w.getframerate())


def ensure_piper() -> str:
    """Return path to piper executable."""
    fixed = "/tmp/klieg-tts/bin/piper"
    if os.path.isfile(fixed):
        return fixed
    for c in ("piper", os.path.expanduser("~/.local/bin/piper")):
        if shutil.which(c) or os.path.isfile(c):
            return shutil.which(c) or c
    venv = os.path.join(WORK, "tts-venv")
    if not os.path.isdir(venv):
        subprocess.run(["uv", "venv", venv, "--python", "3.12"], check=True)
        subprocess.run(
            ["uv", "pip", "install", "--python", f"{venv}/bin/python", "piper-tts"],
            check=True,
        )
    return f"{venv}/bin/piper"


def synth_vo(piper: str, text: str, out_wav: str) -> float:
    os.makedirs(os.path.dirname(out_wav), exist_ok=True)
    # clean path for speech
    spoken = text.replace("github.com slash LangerSword slash hermes-klieg",
                          "github.com slash langer sword slash hermes klieg")
    env = os.environ.copy()
    env["PYTHONPATH"] = ""
    cmd = [piper, "-m", VOICE, "--length-scale", "1.0", "-f", out_wav]
    if piper.endswith("piper") and "tts-venv" in piper:
        pass
    p = subprocess.run(cmd, input=spoken + "\n", text=True, capture_output=True, env=env)
    if p.returncode != 0 or not os.path.exists(out_wav):
        # fallback: espeak-ng
        subprocess.run(
            ["espeak-ng", "-v", "en-gb", "-s", "155", "-w", out_wav, spoken],
            check=True,
        )
    # mono → stereo 48k for mix
    stereo = out_wav.replace(".wav", "_48.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", out_wav,
         "-ar", "48000", "-ac", "2", stereo],
        check=True,
    )
    os.replace(stereo, out_wav)
    return wav_duration(out_wav)


def load_cast():
    data = json.load(open(CAST))
    return data["events"], float(data["duration"])


def cast_text_until(events, t):
    return "".join(text for et, text in events if et <= t)


def film_frames(n=10):
    out = []
    for f in (0, 12, 36, 54, 90, 132, 168, 216, 230, 280):
        p = os.path.join(FILM, "%04d.png" % f)
        if os.path.exists(p):
            out.append((f, p))
    return out[:n]


def draw_terminal(img, text_lines, headline="klieg - live session"):
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 56], fill=PANEL)
    for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        d.ellipse([28 + i * 28, 18, 46 + i * 28, 36], fill=c)
    d.text((140, 16), headline, font=font(MONO, 22), fill=DIM)
    y = 88
    fm = font(MONO, 22)
    for raw in text_lines:
        line = re.sub(r"\x1b\[[0-9;]*m", "", raw).replace("\t", "    ")
        line = line.replace(os.path.expanduser("~"), "~")
        line = re.sub(r"/home/[^/\s]+", "~", line)
        if len(line) > 100:
            line = line[:99] + "…"
        colour = INK
        if line.startswith("$") or line.startswith("klieg"):
            colour = ACC
        if '"ok": false' in line or '"stale"' in line or "stale" in line.lower():
            colour = WARN
        if '"ok": true' in line:
            colour = OK
        d.text((48, y), line, font=fm, fill=colour)
        y += 32
        if y > H - 90:
            break


def draw_sheet(t, items):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((80, 48), "output of that job", font=font(TAG, 44), fill=INK)
    d.text((82, 108), "PNG frames on disk - not a screenshot of a UI mock", font=font(MONO, 22), fill=DIM)
    cols = 5
    cw, ch = 340, 400
    x0, y0 = 70, 170
    for i, (num, path) in enumerate(items):
        cx = x0 + (i % cols) * (cw + 18)
        cy = y0 + (i // cols) * (ch + 20)
        appear = ease((t - i * 0.12) / 0.7)
        if appear <= 0:
            continue
        try:
            im = Image.open(path).convert("RGBA")
            im.thumbnail((cw - 16, ch - 40))
            panel = Image.new("RGB", (cw, ch), (16, 19, 24))
            panel.paste(im, ((cw - im.width) // 2, 28 + (ch - 40 - im.height) // 2), im)
            img.paste(panel, (cx, cy))
        except OSError:
            continue
        d.rectangle([cx, cy, cx + cw, cy + ch], outline=(50, 58, 70))
        d.text((cx + 12, cy + 8), "frame %04d" % num, font=font(MONO, 18), fill=ACC)
    return img


def draw_board(t):
    board = Image.open(BOARD).convert("RGB")
    # fit to frame with slight Ken Burns
    scale = max(W / board.width, H / board.height) * (1.02 + 0.04 * min(1.0, t / 10.0))
    nw, nh = int(board.width * scale), int(board.height * scale)
    board = board.resize((nw, nh), Image.Resampling.LANCZOS)
    ox = max(0, (nw - W) // 2)
    oy = max(0, (nh - H) // 2 - int(20 * math.sin(t / 8)))
    return board.crop((ox, oy, ox + W, oy + H))


def draw_end(nums):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((120, 340), "Klieg", font=font(TAG, 120), fill=INK)
    d.text((126, 480), "a DCC bridge for Hermes", font=font(TAG, 40), fill=DIM)
    d.text((126, 550), "the render that cannot lie about finishing", font=font(MONO, 28), fill=ACC)
    d.text((126, 640), "github.com/LangerSword/hermes-klieg", font=font(MONO, 32), fill=INK)
    d.text((126, 700), f"{nums['tools']} tools  |  {nums['tests']} tests  |  real PTY session",
           font=font(MONO, 24), fill=DIM)
    return img


def build_timeline(vo_durs):
    """Each beat = max(vo + pad, min_picture). Returns beats with absolute times."""
    beats = []
    t = 0.0
    for i, step in enumerate(SCRIPT):
        vo = vo_durs[i]
        # picture hold: VO + 0.8s tail; cold open a bit longer on product
        min_pic = 3.5 if step["mode"] == "cast" else 2.8
        if step["id"] == "result":
            min_pic = 5.0
        if step["id"] == "board":
            min_pic = 6.0
        if step["id"] == "end":
            min_pic = 4.0
        span = max(vo + 0.9, min_pic)
        beats.append({
            **step,
            "start": round(t, 3),
            "end": round(t + span, 3),
            "vo_dur": round(vo, 3),
            "span": round(span, 3),
        })
        t += span
    return beats, t


def main() -> int:
    os.makedirs(FRAMES, exist_ok=True)
    os.makedirs(VO_DIR, exist_ok=True)
    for n in os.listdir(FRAMES):
        os.remove(os.path.join(FRAMES, n))

    events, cast_dur = load_cast()
    nums = counts()
    items = film_frames()
    print("cast", cast_dur, "s | frames", len(items), "|", nums)

    if not os.path.exists(VOICE):
        print("missing voice", VOICE)
        return 1
    piper = ensure_piper()
    print("piper", piper)

    vo_durs = []
    vo_paths = []
    for i, step in enumerate(SCRIPT):
        path = os.path.join(VO_DIR, f"{i:02d}_{step['id']}.wav")
        d = synth_vo(piper, step["vo"], path)
        vo_durs.append(d)
        vo_paths.append(path)
        print(f"  vo {step['id']}: {d:.2f}s")

    beats, total = build_timeline(vo_durs)
    story = {
        "fps": FPS,
        "duration": round(total, 2),
        "beats": [
            {
                "name": b["id"],
                "start": b["start"],
                "end": b["end"],
                "caption": b["caption"],
                "vo": b["vo"],
                "claim": None,
            }
            for b in beats
        ],
        "numbers": nums,
        "audio": "piper-tts original VO for this cut (no third-party project mix)",
    }
    json.dump(story, open(STORY, "w"), indent=1)
    print("total", round(total, 2), "s")

    n_frames = int(total * FPS)
    print("rendering", n_frames, "frames...")
    for i in range(n_frames):
        t = i / FPS
        # find beat
        beat = beats[-1]
        for b in beats:
            if b["start"] <= t < b["end"]:
                beat = b
                break
        local = t - beat["start"]
        img = Image.new("RGB", (W, H), BG)

        if beat["mode"] == "cast":
            # advance cast playhead across the beat
            t0 = float(beat.get("cast_t0") or 0.0)
            # map local time into cast window of ~beat.span * 0.85 of remaining cast
            ct = t0 + local * 0.85
            ct = min(ct, cast_dur - 0.05)
            lines = cast_text_until(events, ct).splitlines()
            # keep last ~28 lines visible
            draw_terminal(img, lines[-28:], headline="klieg - recorded PTY session")
        elif beat["mode"] == "sheet":
            img = draw_sheet(local, items)
        elif beat["mode"] == "board":
            img = draw_board(local)
        else:
            img = draw_end(nums)

        d = ImageDraw.Draw(img)
        if beat["caption"]:
            # lower-third bar
            d.rectangle([0, H - 88, W, H], fill=(10, 12, 16))
            d.text((64, H - 58), beat["caption"], font=font(MONO, 24), fill=DIM)
        d.text((W - 160, H - 58), "klieg", font=font(MONO, 22), fill=ACC)

        img.save(os.path.join(FRAMES, "%04d.png" % i), compress_level=1)
        if i % 90 == 0:
            print(f"  frame {i}/{n_frames}")

    print("encode silent...")
    silent = os.path.join(WORK, "silent.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", str(FPS), "-i", os.path.join(FRAMES, "%04d.png"),
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
               "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x080a0d,fps=30,format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart",
        silent,
    ], check=True)

    # mix VO: adelay each clip to beat start
    print("mix VO...")
    # build filter
    inputs = ["-i", silent]
    filters = []
    labels = []
    for i, (b, vp) in enumerate(zip(beats, vo_paths)):
        inputs += ["-i", vp]
        delay_ms = int(b["start"] * 1000)
        filters.append(f"[{i+1}:a]adelay={delay_ms}|{delay_ms},volume=1.0[v{i}]")
        labels.append(f"[v{i}]")
    filters.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,"
        f"apad=whole_dur={total:.3f},loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
    )
    mixed = os.path.join(WORK, "final.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{total:.3f}",
        "-movflags", "+faststart",
        mixed,
    ], check=True)
    shutil.copy2(mixed, OUT)
    size = os.path.getsize(OUT)
    print("demo:", OUT, size, "bytes", round(total, 1), "s")
    return 0 if size > 400_000 else 1


if __name__ == "__main__":
    raise SystemExit(main())
