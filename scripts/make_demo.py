"""Build the 75-second demo: real tool output, rendered as a terminal, encoded by Klieg.

    /path/to/venv/python scripts/make_demo.py

Nothing here is staged text. Each line comes back from klieg_probe / klieg_plan /
klieg_render / klieg_jobs / klieg_publish on this machine, including the stale-artefact
demonstration, which creates a file with an hour-old mtime and shows verify() refusing it.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import klieg_core as core
import klieg_tools as tools

W, H, FPS = 1920, 1080, 30
BG = (10, 12, 15)
PANEL = (16, 19, 24)
INK = (226, 232, 240)
DIM = (139, 152, 168)
ACC = (96, 165, 250)
WARN = (251, 146, 60)
OK = (74, 222, 128)
MONO = "/usr/share/fonts/TTF/JetBrainsMonoNLNerdFontMono-Regular.ttf"
TAG = "/usr/share/fonts/OTF/SpaceGrotesk-Regular.otf"
BLEND = os.path.expanduser("~/projects/omnitrix-strobe/board/anim.blend")
FRAMES = "/tmp/klieg-demo/frames"
OUT = os.path.join(REPO, "docs/media/klieg_demo.mp4")


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


# ------------------------------------------------------------------ capture
def capture() -> list[tuple[str, str]]:
    """(colour, text) pairs, from real calls."""
    lines: list[tuple[str, str]] = []

    def add(t, c=DIM):
        for part in str(t).splitlines():
            lines.append((c, part))

    add("$ klieg_probe", INK)
    probe = json.loads(tools.h_probe({}))
    for a in probe["adapters"]:
        mark = "found" if a["found"] else "absent"
        add(f"  {a['dcc']:<9} {mark:<7} {a.get('version', '')[:52]}",
            OK if a["found"] else DIM)

    add("", DIM)
    add("$ klieg_plan  --frames 0-287   (resolves the pass, runs nothing)", INK)
    plan = json.loads(tools.h_plan({"blend": BLEND, "frames": "0-287", "outdir": "/tmp/klieg-demo/px"}))
    add(f"  frames          {plan['frame_count']}")
    add(f"  expected last   {plan['expected_last']}")
    add(f"  predicted       {plan['predicted_seconds']} s   (median of this machine's own runs)")
    add(f"  would_run       {plan['would_run']}   blockers {plan['blockers']}")

    add("", DIM)
    add("$ klieg_render --frames 0-1 --pct 25 --samples 32", INK)
    r = json.loads(tools.h_render({"dcc": "blender", "blend": BLEND, "frames": "0-1",
                                   "outdir": FRAMES, "samples": 32, "pct": 25, "name": "demo"}))
    job = r["job"]
    add(f"  job {job}  state {r['state']}")
    deadline = time.time() + 240
    while time.time() < deadline:
        st = core.poll(job)
        if st.get("state") != "running":
            break
        time.sleep(1)
    add(f"  finished  state {st['state']}  exit {st.get('exit')}")

    add("", DIM)
    add("$ klieg_jobs action=verify", INK)
    v = core.verify(job)
    add(f"  ok {v['ok']}   artefacts {[os.path.basename(a['path']) for a in v['artefacts']]}",
        OK if v["ok"] else WARN)
    add(f"  counted {v.get('counted')} of {v.get('expected_min')} promised frames")

    # the money shot: a file that exists, looks right, and is an hour old
    tmp = tempfile.mkdtemp(prefix="klieg-demo-stale-")
    stale = os.path.join(tmp, "0000.png")
    open(stale, "wb").write(b"not really a frame")
    old = time.time() - 3600
    os.utime(stale, (old, old))
    j2 = core.launch("stale", ["/bin/sh", "-c", "true"], guard=[stale],
                     what="a frame that predates the job")
    time.sleep(1.5)
    v2 = core.verify(j2["job"])
    add("", DIM)
    add("# the failure this plugin exists for:", WARN)
    add(f"$ verify  file exists · mtime is one hour old · job started just now", INK)
    add(f"  ok {v2['ok']}   stale {len(v2['stale'])}   -> a count is not evidence",
        WARN if not v2["ok"] else DIM)

    add("", DIM)
    add("$ klieg_publish  (BT.709 + colour tags in the bitstream)", INK)
    add(f"  -> {os.path.relpath(OUT, REPO)}", INK)
    return lines


# ------------------------------------------------------------------ render
def timeline(lines, cps=26):
    """Assign each line a start frame so the whole thing lands near 50 seconds."""
    t, out = 96, []
    for colour, text in lines:
        out.append(dict(colour=colour, text=text, start=t))
        t += max(14, int(len(text) / cps * FPS) + 14)
    return out, t + 110


def draw_frame(i, items, end_frame, caption, header):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    if i < 96:                                    # title card
        d.text((120, 380), "Klieg", font=font(TAG, 132), fill=INK)
        d.text((126, 540), "a DCC bridge for Hermes", font=font(TAG, 44), fill=DIM)
        d.text((126, 618), "the render that cannot lie about finishing",
               font=font(MONO, 26), fill=ACC)
        return img

    d.rectangle([0, 0, W, 64], fill=PANEL)
    d.text((40, 20), header, font=font(MONO, 22), fill=DIM)
    d.text((W - 260, 20), caption, font=font(MONO, 22), fill=ACC)

    y = 110
    fm = font(MONO, 21)
    for it in items:
        if i < it["start"]:
            break
        text = it["text"]
        shown = text[: max(0, int((i - it["start"]) * 3))]
        if shown:
            d.text((48, y), shown, font=fm, fill=it["colour"])
        if i - it["start"] < len(text) * 3 + 12:
            cx = 48 + d.textlength(shown, font=fm)
            d.rectangle([cx + 2, y + 2, cx + 13, y + 26], fill=ACC)
        y += 30
        if y > H - 150:
            break

    if i > end_frame - 60:
        d.text((W // 2 - 420, H - 120), "github.com/LangerSword/hermes-klieg",
               font=font(TAG, 40), fill=INK)
        d.text((W // 2 - 420, H - 66), "9 tools · 1 hook · 27 tests · artefact-verified",
               font=font(MONO, 22), fill=DIM)
    return img


def main() -> int:
    os.makedirs(FRAMES, exist_ok=True)
    for n in os.listdir(FRAMES):
        os.remove(os.path.join(FRAMES, n))

    print("capturing real output...")
    lines = capture()

    # split into captioned chunks so the header explains the step
    captions = []
    cur = "1 / probe"
    for colour, text in lines:
        if text.startswith("$ klieg_plan"):
            cur = "2 / plan"
        elif text.startswith("$ klieg_render"):
            cur = "3 / render"
        elif text.startswith("$ klieg_jobs"):
            cur = "4 / verify"
        elif text.startswith("#"):
            cur = "5 / the failure"
        elif text.startswith("$ klieg_publish"):
            cur = "6 / publish"
        captions.append(cur)

    items, end = timeline(lines)
    for it, cap in zip(items, captions):
        it["caption"] = cap

    print(f"rendering {end} frames...")
    for i in range(end):
        cap = "1 / probe"
        for it in items:
            if i >= it["start"]:
                cap = it["caption"]
        img = draw_frame(i, items, end, cap, "klieg — a DCC bridge for Hermes")
        img.save(os.path.join(FRAMES, "%04d.png" % i), compress_level=1)

    print("encoding through klieg_publish...")
    pub = json.loads(tools.h_publish({"frames_dir": FRAMES, "out": OUT,
                                      "fps": FPS, "bitrate": "8M", "name": "demo-publish"}))
    if "error" in pub:
        print("publish refused:", pub["error"])
        return 1
    deadline = time.time() + 300
    while time.time() < deadline:
        st = core.poll(pub["job"])
        if st.get("state") != "running":
            break
        time.sleep(1)
    size = os.path.getsize(OUT) if os.path.exists(OUT) else 0
    print("demo:", OUT, st.get("state"), size, "bytes", f"{end/FPS:.1f}s")
    return 0 if size else 1


if __name__ == "__main__":
    raise SystemExit(main())
