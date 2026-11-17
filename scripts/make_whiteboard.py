"""Draw the Klieg architecture whiteboard, 1600x900, no drawing app involved.

    python3 scripts/make_whiteboard.py
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "docs/media/whiteboard.png")

W, H = 1600, 900
BG = (11, 13, 16)
INK = (226, 232, 240)
DIM = (138, 150, 166)
ACCENT = (96, 165, 250)
WARN = (251, 146, 60)
EDGE = (58, 66, 78)

MONO = "/usr/share/fonts/TTF/JetBrainsMonoNLNerdFontMono-Regular.ttf"
TAG = "/usr/share/fonts/OTF/SpaceGrotesk-Regular.otf"


def f(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def box(d, xy, title, lines, colour=EDGE, accent=INK):
    d.rounded_rectangle(xy, radius=14, outline=colour, width=2, fill=(17, 20, 25))
    x0, y0, x1, y1 = xy
    d.text((x0 + 18, y0 + 14), title, font=f(TAG, 26), fill=accent)
    y = y0 + 54
    # drawn blind, so measure: a line wider than the interior is a bug, not a style choice
    interior = (x1 - x0) - 36
    for ln in lines:
        fm = f(MONO, 15)
        w = d.textlength(ln, font=fm)
        if w > interior:
            print(f"OVERFLOW box '{title}': {w:.0f}px > {interior}px :: {ln}")
        d.text((x0 + 18, y), ln, font=fm, fill=DIM)
        y += 24
    if y > y1:
        print(f"OVERFLOW box '{title}': text bottom {y} > box bottom {y1}")


def arrow(d, a, b, colour=EDGE, label=None):
    d.line([a, b], fill=colour, width=2)
    # arrowhead
    (x0, y0), (x1, y1) = a, b
    import math
    ang = math.atan2(y1 - y0, x1 - x0)
    for s in (+0.42, -0.42):
        d.line([(x1, y1), (x1 - 16 * math.cos(ang - s), y1 - 16 * math.sin(ang - s))],
               fill=colour, width=2)
    if label:
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        d.text((mx - 40, my - 26), label, font=f(MONO, 15), fill=DIM)


def main() -> int:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((60, 46), "Klieg", font=f(TAG, 54), fill=INK)
    d.text((60, 108), "a DCC bridge for Hermes  ·  the render that cannot lie about finishing",
           font=f(TAG, 24), fill=DIM)

    # agent
    box(d, (60, 190, 400, 350), "Hermes agent", [
        "klieg_probe   what is installed",
        "klieg_plan    resolve, don't run",
        "klieg_render  start a pass",
        "klieg_gate    numbers, no verdict",
    ], accent=INK)

    # approval gate
    box(d, (430, 190, 790, 350), "pre_tool_call gate", [
        "5 verbs execute code or GPU",
        "→ approval, rule_key klieg:*",
        "read-only verbs pass silently",
        "unattended runs fail closed",
    ], accent=ACCENT)

    # adapters
    box(d, (810, 150, 1150, 380), "adapters (one file each)", [
        "Blender    blender -b … -P script",
        "Houdini    hython script.py",
        "Nuke       nuke -t script.py",
        "C4D        version probe",
        "AE/Resolve declared, not driven",
        "PATH sanitised: /usr/bin:/bin",
    ], accent=INK)

    # hosts
    box(d, (1200, 170, 1540, 300), "host processes", [
        "PID, own session",
        "no inherited secrets",
        "13-variable env allow-list",
    ], accent=DIM)

    # job dir
    box(d, (430, 430, 860, 620), "job directory", [
        "status.json   state / pid / frames",
        "log.txt       capped at 8 MiB",
        "exit          written BY the child",
        "",
        "queued → running → done | failed | killed",
    ], accent=INK)

    box(d, (910, 430, 1540, 620), "verify() — the only claim that matters", [
        "artefact exists?",
        "  AND mtime >= job start?",
        "  AND count >= frames promised?",
        "",
        "a stale frame and a short render are both failures",
    ], accent=WARN)

    # gpu lock
    box(d, (60, 430, 380, 620), "one GPU, one render", [
        "lock per host, pid-held",
        "second request → queued",
        "position reported",
        "queue=false → refused",
        "dead holder reaped",
    ], accent=ACCENT)

    # flow arrows
    arrow(d, (380, 260), (430, 260), label="tools")
    arrow(d, (760, 260), (810, 260), label="argv")
    arrow(d, (1150, 260), (1200, 260), label="spawn")
    arrow(d, (1290, 380), (1290, 430), label="writes")
    arrow(d, (860, 525), (910, 525), label="checked by")
    arrow(d, (380, 525), (430, 525), label="lock")

    # the failure story
    d.text((60, 690), "the failure this exists for", font=f(TAG, 26), fill=WARN)
    d.text((60, 736),
           "rebuild failed → old blend still on disk → job emits 288 frames of the previous geometry → exit 0.",
           font=f(MONO, 17), fill=DIM)
    d.text((60, 766),
           "a frame count is not evidence.   mtime(newest artefact) > started_at(job) is.",
           font=f(MONO, 17), fill=INK)

    d.text((60, 830), "github.com/LangerSword/hermes-klieg", font=f(MONO, 18), fill=ACCENT)
    d.text((W - 330, 830), "27 tests · 9 tools · 1 hook", font=f(MONO, 18), fill=DIM)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT)
    print("wrote", OUT, img.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
