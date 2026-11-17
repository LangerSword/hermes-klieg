"""The Klieg whiteboard, drawn the way the Pilot diagram is drawn.

Cream board with a faint grid, four big pastel shapes, thick marker outlines, handwritten
labels, coloured arrows, a sticky note and a star. Deliberately sparse: if a box needs a
sixth line, the box is wrong.

Numbers on the card are read at build time - tools from plugin.yaml, tests from an actual
test run - so the drawing cannot claim a count the code does not have.

    python3 scripts/make_whiteboard.py
"""

from __future__ import annotations

import math
import os
import random
import re
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "docs/media/whiteboard.png")

W, H = 1600, 900
PAPER = (251, 246, 232)
GRID = (235, 227, 209)
INK = (32, 32, 34)
GREY = (122, 118, 110)
BLUE = (30, 105, 220)
BLUE_F = (219, 233, 252)
PURPLE = (108, 66, 228)
PURPLE_F = (231, 224, 252)
GREEN = (38, 150, 66)
GREEN_F = (216, 243, 221)
ORANGE = (226, 84, 14)
ORANGE_F = (253, 229, 214)
YELLOW = (255, 210, 58)
RED = (206, 48, 44)

HAND = "/usr/share/fonts/Caveat-VariableFont_wght.ttf"
RNG = random.Random(11)


def hand(size, weight=None):
    try:
        f = ImageFont.truetype(HAND, size)
        if weight and hasattr(f, "set_variation_by_axes"):
            f.set_variation_by_axes([weight])
        return f
    except OSError:
        return ImageFont.load_default()


def paper(w, h):
    base = np.full((h, w, 3), PAPER, np.uint8)
    rng = np.random.default_rng(3)
    base = np.clip(base.astype(np.int16) + rng.integers(-7, 8, (h, w, 1), dtype=np.int16),
                   0, 255).astype(np.uint8)
    img = Image.fromarray(base)
    d = ImageDraw.Draw(img, "RGBA")
    for x in range(0, w, 44):
        d.line([(x, 0), (x + RNG.randint(-1, 1), h)], fill=(*GRID, 150), width=1)
    for y in range(0, h, 44):
        d.line([(0, y), (w, y + RNG.randint(-1, 1))], fill=(*GRID, 150), width=1)
    return img


def stroke(d, pts, colour, width=3, alpha=255, passes=2, amp=1.7):
    for p in range(passes):
        wob = [(x + RNG.uniform(-amp, amp), y + RNG.uniform(-amp, amp)) for x, y in pts]
        d.line(wob, fill=(*colour, alpha), width=max(1, width - p), joint="curve")


def shape(d, box, radius, colour, fill):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=radius, fill=(*fill, 190))
    for amp, w in ((1.4, 4), (2.4, 3), (0.8, 2)):
        b = (x0 + RNG.uniform(-amp, amp), y0 + RNG.uniform(-amp, amp),
             x1 + RNG.uniform(-amp, amp), y1 + RNG.uniform(-amp, amp))
        d.rounded_rectangle(b, radius=radius + RNG.uniform(-2, 2), outline=(*colour, 255), width=w)


def title(d, xy, text, colour, size=76):
    f = hand(size, 700)
    d.text(xy, text, font=f, fill=colour)
    w = d.textlength(text, font=f)
    stroke(d, [(xy[0] + 4, xy[1] + size * 1.02), (xy[0] + w * 0.95, xy[1] + size * 1.0)],
           colour, width=4, amp=2.6)


def label(d, xy, text, colour, size=30):
    d.text(xy, text, font=hand(size), fill=colour)


def arrow(d, a, b, colour, width=4, dashed=False, curve=0.0, tag=None, tag_off=(0, -30)):
    ax, ay = a
    bx, by = b
    mx, my = (ax + bx) / 2, (ay + by) / 2 + curve
    pts = [((1 - t) ** 2 * ax + 2 * (1 - t) * t * mx + t ** 2 * bx,
            (1 - t) ** 2 * ay + 2 * (1 - t) * t * my + t ** 2 * by)
           for t in (i / 26 for i in range(27))]
    if dashed:
        for i in range(0, len(pts) - 1, 2):
            stroke(d, pts[i:i + 2], colour, width, passes=1, amp=0.9)
    else:
        stroke(d, pts, colour, width)
    ang = math.atan2(by - pts[-3][1], bx - pts[-3][0])
    for s in (+0.5, -0.5):
        stroke(d, [(bx, by), (bx - 20 * math.cos(ang + s), by - 20 * math.sin(ang + s))],
               colour, width, passes=1, amp=0.9)
    if tag:
        d.text((mx + tag_off[0], my + tag_off[1]), tag, font=hand(28), fill=colour)


def sticky(img, xy, lines, angle=-5):
    w, h = 330, 168
    note = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(note)
    d.rectangle([5, 5, w - 5, h - 5], fill=(*YELLOW, 240))
    for amp in (1.2, 2.0):
        d.rectangle([5 + RNG.uniform(-amp, amp), 5 + RNG.uniform(-amp, amp),
                     w - 5 + RNG.uniform(-amp, amp), h - 5 + RNG.uniform(-amp, amp)],
                    outline=(214, 168, 26, 255), width=2)
    d.text((22, 14), lines[0], font=hand(38, 650), fill=(48, 40, 22))
    y = 66
    for ln in lines[1:]:
        d.text((22, y), ln, font=hand(29), fill=(72, 62, 40))
        y += 34
    bicubic = getattr(getattr(Image, "Resampling", Image), "BICUBIC")
    note = note.rotate(angle, expand=True, resample=bicubic)
    img.paste(note, xy, note)


def star(d, cx, cy, r, colour):
    for ang in (0, math.pi / 2):
        stroke(d, [(cx - r * math.cos(ang), cy - r * math.sin(ang)),
                   (cx + r * math.cos(ang), cy + r * math.sin(ang))],
               colour, width=3, passes=1, amp=1.0)


def counts():
    tools = len(re.findall(r"^\s+- klieg_", open(os.path.join(REPO, "plugin.yaml")).read(), re.M))
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                       cwd=REPO, capture_output=True, text=True)
    m = re.search(r"Ran (\d+) tests", r.stderr + r.stdout)
    return tools, int(m.group(1)) if m else 0


def main() -> int:
    tools, tests = counts()
    img = paper(W, H)
    d = ImageDraw.Draw(img, "RGBA")

    title(d, (70, 34), "how klieg works", INK)
    label(d, (74, 148), "a dcc bridge for hermes", GREY, 36)

    # --- three shapes across the top
    shape(d, (70, 215, 405, 385), 22, BLUE, BLUE_F)
    label(d, (96, 232), "Hermes agent", BLUE, 46)
    label(d, (96, 300), "klieg_render", (58, 58, 62), 31)
    label(d, (96, 338), "klieg_verify", (58, 58, 62), 31)

    shape(d, (470, 215, 800, 385), 22, PURPLE, PURPLE_F)
    label(d, (496, 232), "klieg", PURPLE, 46)
    label(d, (496, 300), "plan · render", (58, 58, 62), 31)
    label(d, (496, 338), "jobs · verify", (58, 58, 62), 31)

    shape(d, (865, 185, 1520, 415), 22, GREEN, GREEN_F)
    label(d, (893, 202), "the job", GREEN, 46)
    label(d, (893, 268), "status.json · log.txt · exit", (52, 62, 54), 31)
    label(d, (893, 306), "queued → running → done", (52, 62, 54), 31)
    label(d, (893, 344), "exit is written by the child", (52, 62, 54), 29)

    arrow(d, (405, 300), (468, 300), BLUE, tag="argv")
    arrow(d, (800, 300), (863, 300), PURPLE, tag="spawn")
    arrow(d, (1100, 415), (940, 470), GREEN, dashed=True, curve=26, tag="mtime proof",
          tag_off=(-30, 24))

    # --- bottom left: the GPU lock
    shape(d, (70, 520, 470, 690), 22, ORANGE, ORANGE_F)
    label(d, (96, 536), "your GPU", ORANGE, 46)
    label(d, (96, 600), "one render at a time", (66, 52, 42), 30)
    label(d, (96, 640), "the second one queues", (66, 52, 42), 30)
    arrow(d, (470, 605), (960, 440), ORANGE, curve=-120, tag="when free", tag_off=(-20, 26))

    sticky(img, (1180, 520), ["a frame count", "is not evidence.", "mtime > start."])
    star(d, 1495, 300, 46, ORANGE)
    star(d, 180, 185, 26, BLUE)

    label(d, (70, 838), "github.com/LangerSword/hermes-klieg · MIT", GREY, 30)
    note = "no count. a proof."
    nw = d.textlength(note, font=hand(36, 650))
    d.text((W - 80 - nw, 826), note, font=hand(36, 650), fill=RED)
    label(d, (930, 838), f"{tools} tools · {tests} tests", GREY, 30)

    img = img.filter(ImageFilter.GaussianBlur(0.3))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT, optimize=True)
    print("wrote", OUT, img.size, f"({tools} tools, {tests} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
