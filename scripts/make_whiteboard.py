"""Hand-drawn ETHGlobal-style whiteboard for how Klieg works.

Marker on slightly dirty board — jittered strokes, Caveat lettering,
not UI cards. Look like a hackathon wall sketch.

    python3 scripts/make_whiteboard.py
"""

from __future__ import annotations

import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "docs/media/whiteboard.png")

W, H = 1600, 900
# board paper
PAPER = (236, 232, 220)
INK_BLACK = (28, 30, 36)
INK_BLUE = (30, 64, 140)
INK_RED = (160, 42, 36)
INK_GREEN = (28, 96, 58)
INK_ORANGE = (180, 90, 20)
FAINT = (120, 118, 110)

HAND = "/usr/share/fonts/Caveat-VariableFont_wght.ttf"
MONO = "/usr/share/fonts/TTF/JetBrainsMonoNLNerdFontMono-Regular.ttf"
SANS = "/usr/share/fonts/OTF/SpaceGrotesk-Regular.otf"

RNG = random.Random(42)


def f(path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def paper_texture(w: int, h: int) -> Image.Image:
    """Off-white board with grain, faint grid ghosts, coffee-ish stain."""
    base = np.full((h, w, 3), PAPER, dtype=np.uint8)
    rng = np.random.default_rng(7)
    noise = rng.integers(-14, 15, (h, w, 1), dtype=np.int16)
    base = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(base)
    d = ImageDraw.Draw(img, "RGBA")
    # faint horizontal guide lines like a real board
    for y in range(70, h - 40, 38):
        a = 18 + (y % 7)
        d.line([(40, y + RNG.randint(-1, 1)), (w - 40, y + RNG.randint(-1, 1))],
               fill=(*FAINT, a), width=1)
    # soft corner vignette / tape marks
    for cx, cy in ((80, 70), (w - 90, 75), (70, h - 80), (w - 85, h - 70)):
        d.ellipse([cx - 18, cy - 12, cx + 18, cy + 12], fill=(200, 190, 170, 90))
    # coffee ring
    d.ellipse([1180, 620, 1320, 760], outline=(170, 140, 110, 55), width=6)
    d.ellipse([1190, 630, 1310, 750], outline=(170, 140, 110, 30), width=3)
    return img


def jitter_line(
    d: ImageDraw.ImageDraw,
    a: tuple[float, float],
    b: tuple[float, float],
    colour,
    width: int = 3,
    wobble: float = 2.4,
    segs: int = 18,
) -> None:
    """Polyline with hand wobble instead of a ruler line."""
    x0, y0 = a
    x1, y1 = b
    pts = []
    for i in range(segs + 1):
        t = i / segs
        x = x0 + (x1 - x0) * t + RNG.uniform(-wobble, wobble)
        y = y0 + (y1 - y0) * t + RNG.uniform(-wobble, wobble)
        pts.append((x, y))
    d.line(pts, fill=colour, width=width, joint="curve")


def hand_box(
    d: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    colour=INK_BLACK,
    width: int = 3,
) -> None:
    x0, y0, x1, y1 = xy
    # four imperfect sides, slight overshoot at corners
    jitter_line(d, (x0 - 2, y0), (x1 + 3, y0 + RNG.uniform(-2, 2)), colour, width)
    jitter_line(d, (x1, y0 - 1), (x1 + RNG.uniform(-2, 2), y1 + 2), colour, width)
    jitter_line(d, (x1 + 2, y1), (x0 - 3, y1 + RNG.uniform(-2, 2)), colour, width)
    jitter_line(d, (x0, y1 + 1), (x0 + RNG.uniform(-2, 2), y0 - 2), colour, width)


def hand_arrow(
    d: ImageDraw.ImageDraw,
    a: tuple[float, float],
    b: tuple[float, float],
    colour=INK_BLUE,
    label: str | None = None,
) -> None:
    jitter_line(d, a, b, colour, width=3, wobble=1.8, segs=14)
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    for s in (+0.55, -0.55):
        hx = b[0] - 18 * math.cos(ang + s)
        hy = b[1] - 18 * math.sin(ang + s)
        jitter_line(d, b, (hx, hy), colour, width=3, wobble=0.6, segs=4)
    if label:
        mx = (a[0] + b[0]) / 2 + RNG.uniform(-6, 6)
        my = (a[1] + b[1]) / 2 - 22 + RNG.uniform(-4, 4)
        d.text((mx - 20, my), label, font=f(HAND, 28), fill=colour)


def scribble_title(d: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], size: int, colour) -> None:
    d.text(xy, text, font=f(HAND, size), fill=colour)
    # underline scribble
    x, y = xy
    try:
        bb = d.textbbox(xy, text, font=f(HAND, size))
        w = bb[2] - bb[0]
    except Exception:
        w = len(text) * size * 0.45
    jitter_line(d, (x, y + size * 0.95), (x + w * 0.92, y + size * 0.95 + 3), colour, width=2, wobble=1.2)


def bullet(d: ImageDraw.ImageDraw, x: int, y: int, text: str, colour=INK_BLACK, size: int = 26) -> int:
    d.text((x, y), "•  " + text, font=f(HAND, size), fill=colour)
    return y + int(size * 1.15)


def main() -> int:
    img = paper_texture(W, H)
    d = ImageDraw.Draw(img)

    # header like a hacker wrote it at 2am
    scribble_title(d, "KLIEG", (70, 36), 78, INK_BLACK)
    d.text((280, 58), "— DCC bridge for Hermes", font=f(HAND, 40), fill=INK_BLUE)
    d.text(
        (70, 118),
        "how a render job stops lying about finishing  (ETH-style wall notes)",
        font=f(HAND, 30),
        fill=INK_ORANGE,
    )

    # --- boxes as freehand regions ---
    # 1 agent
    hand_box(d, (60, 180, 380, 400), INK_BLACK, 3)
    d.text((78, 190), "1. Hermes agent", font=f(HAND, 36), fill=INK_BLACK)
    y = 240
    for line in (
        "klieg_probe   what's installed",
        "klieg_plan    resolve, don't run",
        "klieg_render  start the pass",
        "klieg_jobs    list / verify / kill",
    ):
        y = bullet(d, 78, y, line, INK_BLACK, 24)

    # 2 gate
    hand_box(d, (430, 180, 760, 400), INK_BLUE, 3)
    d.text((448, 190), "2. approval gate", font=f(HAND, 36), fill=INK_BLUE)
    y = 240
    for line in (
        "5 verbs = code or GPU time",
        "rule_key klieg:*  → human ok",
        "probe/scene stay silent",
        "unattended = fail closed",
    ):
        y = bullet(d, 448, y, line, INK_BLUE, 24)

    # 3 adapter
    hand_box(d, (810, 160, 1180, 420), INK_GREEN, 3)
    d.text((828, 170), "3. one adapter / host", font=f(HAND, 34), fill=INK_GREEN)
    y = 220
    for line in (
        "Blender  blender -b … -P",
        "Houdini  hython …",
        "Nuke     nuke -t …",
        "C4D / AE / Resolve declared",
        "PATH scrubbed → /usr/bin:/bin",
        "(pyenv steals Blender's stdlib)",
    ):
        y = bullet(d, 828, y, line, INK_GREEN, 23)

    # 4 host
    hand_box(d, (1220, 180, 1540, 360), INK_BLACK, 3)
    d.text((1238, 190), "4. host process", font=f(HAND, 34), fill=INK_BLACK)
    y = 240
    for line in (
        "own session / PID",
        "no leaked secrets",
        "13-var env allow-list",
    ):
        y = bullet(d, 1238, y, line, INK_BLACK, 24)

    # arrows top row
    hand_arrow(d, (380, 290), (430, 290), INK_BLUE, "tools")
    hand_arrow(d, (760, 290), (810, 290), INK_BLUE, "argv")
    hand_arrow(d, (1180, 270), (1220, 270), INK_BLUE, "spawn")

    # 5 gpu lock
    hand_box(d, (60, 450, 380, 660), INK_ORANGE, 3)
    d.text((78, 460), "5. one GPU lock", font=f(HAND, 34), fill=INK_ORANGE)
    y = 510
    for line in (
        "lock keyed by host",
        "2nd render → queued",
        "position reported",
        "queue=false → refuse",
    ):
        y = bullet(d, 78, y, line, INK_ORANGE, 24)

    # 6 job dir
    hand_box(d, (430, 450, 860, 660), INK_BLACK, 3)
    d.text((448, 460), "6. job directory", font=f(HAND, 34), fill=INK_BLACK)
    y = 510
    for line in (
        "status.json  state / pid / frames",
        "log.txt      capped 8 MiB",
        "exit         written BY the child",
        "queued → running → done|failed",
    ):
        y = bullet(d, 448, y, line, INK_BLACK, 24)

    # 7 verify — the punchline box
    hand_box(d, (910, 450, 1540, 660), INK_RED, 4)
    d.text((928, 460), "7. verify()  ← the only claim", font=f(HAND, 34), fill=INK_RED)
    y = 515
    for line in (
        "artefact exists?",
        "AND mtime >= job start?",
        "AND count >= frames promised?",
        "",
        "stale frames + short renders = FAIL",
    ):
        if line:
            y = bullet(d, 928, y, line, INK_RED, 26)
        else:
            y += 10

    hand_arrow(d, (380, 555), (430, 555), INK_ORANGE, "lock")
    hand_arrow(d, (860, 555), (910, 555), INK_RED, "checked")
    hand_arrow(d, (1360, 360), (1360, 450), INK_BLACK, "writes")

    # failure story — marker banner
    jitter_line(d, (60, 700), (1540, 700), INK_RED, width=2, wobble=1.0, segs=40)
    d.text((70, 710), "the failure this exists for", font=f(HAND, 32), fill=INK_RED)
    d.text(
        (70, 755),
        "rebuild failed → old .blend still on disk → job emits 288 frames of PREVIOUS geometry → exit 0",
        font=f(HAND, 28),
        fill=INK_BLACK,
    )
    d.text(
        (70, 800),
        "a frame COUNT is not evidence.   mtime(newest artefact) > started_at(job)  is.",
        font=f(HAND, 30),
        fill=INK_BLUE,
    )

    d.text((70, 850), "github.com/LangerSword/hermes-klieg", font=f(HAND, 28), fill=INK_GREEN)
    d.text((1180, 850), "9 tools · 1 hook · 27 tests", font=f(HAND, 26), fill=FAINT)

    # slight paper blur + contrast like a phone photo of a board
    img = img.filter(ImageFilter.GaussianBlur(radius=0.35))
    img = ImageEnhance.Contrast(img).enhance(1.08)
    img = ImageEnhance.Color(img).enhance(0.92)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT, optimize=True)
    print("wrote", OUT, img.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
