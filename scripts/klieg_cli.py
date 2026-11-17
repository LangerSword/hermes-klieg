#!/usr/bin/env python3
"""klieg — thin CLI over the tool handlers, for terminals, scripts and demos.

    python3 scripts/klieg_cli.py probe
    python3 scripts/klieg_cli.py plan --blend a.blend --frames 0-287 --out /tmp/px
    python3 scripts/klieg_cli.py render --blend a.blend --frames 0-1 --out /tmp/px --pct 25
    python3 scripts/klieg_cli.py jobs status --job <id>
    python3 scripts/klieg_cli.py publish --frames /tmp/px --out /tmp/x.mp4
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import klieg_tools as T


def show(obj: dict, keys=None) -> None:
    if keys:
        obj = {k: obj.get(k) for k in keys if k in obj}
    print(json.dumps(obj, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser(prog="klieg", description="DCC bridge for Hermes")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="what is installed")

    p = sub.add_parser("plan", help="resolve a render without running it")
    p.add_argument("--blend", required=True)
    p.add_argument("--frames", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--samples", type=int, default=128)
    p.add_argument("--pct", type=int, default=100)
    p.add_argument("--dcc", default="blender")

    r = sub.add_parser("render", help="start a render job")
    r.add_argument("--blend", required=True)
    r.add_argument("--frames", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--samples", type=int, default=128)
    r.add_argument("--pct", type=int, default=100)
    r.add_argument("--dcc", default="blender")
    r.add_argument("--name", default="render")

    j = sub.add_parser("jobs", help="inspect jobs")
    j.add_argument("action", choices=["list", "queue", "status", "log", "verify", "kill"])
    j.add_argument("--job", default="")
    j.add_argument("--lines", type=int, default=20)

    pub = sub.add_parser("publish", help="encode frames")
    pub.add_argument("--frames", required=True)
    pub.add_argument("--out", required=True)
    pub.add_argument("--audio", default=None)
    pub.add_argument("--fps", type=int, default=30)

    a = ap.parse_args()

    if a.cmd == "probe":
        res = json.loads(T.h_probe({}))
        for ad in res["adapters"]:
            state = ad.get("version", "") if ad["found"] else "not installed"
            print(f"  {ad['dcc']:<9} {state}")
        return 0

    if a.cmd == "plan":
        res = json.loads(T.h_plan({"dcc": a.dcc, "blend": a.blend, "frames": a.frames,
                                   "outdir": a.out, "samples": a.samples, "pct": a.pct}))
        show(res, ["frame_count", "expected_last", "predicted_seconds", "would_run",
                   "blockers", "warnings"])
        return 0 if res.get("would_run") else 2

    if a.cmd == "render":
        res = json.loads(T.h_render({"dcc": a.dcc, "blend": a.blend, "frames": a.frames,
                                     "outdir": a.out, "samples": a.samples, "pct": a.pct,
                                     "name": a.name}))
        show(res)
        return 0 if res.get("state") in ("running", "queued") else 1

    if a.cmd == "jobs":
        res = json.loads(T.h_jobs({"action": a.action, "job": a.job, "lines": a.lines}))
        show(res)
        return 0

    if a.cmd == "publish":
        res = json.loads(T.h_publish({"frames_dir": a.frames, "out": a.out,
                                      "audio": a.audio, "fps": a.fps, "name": "publish"}))
        show(res)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
