"""End-to-end proof through Klieg itself: render 2 frames, verify them, encode them.

This is the artefact the README points at: not the framework's own tests, but the
plugin driving Blender and ffmpeg to produce a file.

    python3 scripts/e2e.py [blend]

Writes to /tmp/klieg-e2e/ and prints the verification and the encode path.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import klieg_core as core
import klieg_tools as tools
from paths import resolve_input

BLEND = resolve_input("blend", sys.argv[1] if len(sys.argv) > 1 else None)
OUT = "/tmp/klieg-e2e/frames"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINAL = os.path.join(REPO, "docs/media/e2e_ig.mp4")


def main() -> int:
    if not os.path.exists(BLEND):
        print("no blend at", BLEND)
        return 2

    print("1. render 2 frames through klieg_render (25 %, 32 samples)")
    res = json.loads(tools.h_render({
        "dcc": "blender", "blend": BLEND, "frames": "0-1",
        "outdir": OUT, "samples": 32, "pct": 25, "name": "e2e",
    }))
    if "error" in res:
        print("   refused:", res["error"])
        return 1
    job = res["job"]
    print("   job", job, "pid", res["pid"])

    deadline = time.time() + 300
    while time.time() < deadline:
        st = core.poll(job)
        if st.get("state") != "running":
            break
        time.sleep(2)
    print("   state:", st.get("state"), "exit:", st.get("exit"))

    print("2. verify: artefacts must be newer than the job")
    v = core.verify(job)
    print("   ok:", v["ok"], "artefacts:", [os.path.basename(a["path"]) for a in v["artefacts"]],
          "stale:", len(v["stale"]), "missing:", len(v["missing"]))
    if not v["ok"]:
        print("   log tail:")
        print(core.tail(job, 12))
        return 1

    print("3. publish: BT.709 encode of what was just rendered")
    pub = json.loads(tools.h_publish({
        "frames_dir": OUT, "out": FINAL,
        "fps": 30, "bitrate": "4M", "name": "e2e-publish",
    }))
    if "error" in pub:
        print("   refused:", pub["error"])
        return 1
    pj = pub["job"]
    deadline = time.time() + 180
    while time.time() < deadline:
        pst = core.poll(pj)
        if pst.get("state") != "running":
            break
        time.sleep(1)
    pv = core.verify(pj)
    size = os.path.getsize("/tmp/klieg-e2e/e2e_ig.mp4") if os.path.exists("/tmp/klieg-e2e/e2e_ig.mp4") else 0
    print("   state:", pst.get("state"), "verify:", pv["ok"], "bytes:", size)

    print("\nE2E", "OK" if (v["ok"] and pv["ok"] and size > 0) else "FAILED")
    return 0 if (v["ok"] and pv["ok"] and size > 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
