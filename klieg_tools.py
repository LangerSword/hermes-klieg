"""The tool surface: eight verbs that cover a shot, not eighty that cover a UI."""

from __future__ import annotations

import json
import os
import subprocess
import time

try:  # loaded as a Hermes plugin package
    from . import klieg_adapters as A
    from . import klieg_core as core
    from . import klieg_bridge as bridge_mod
    from . import klieg_colour as colour_mod
    from . import klieg_taste as taste_mod
except ImportError:  # loaded standalone (tests, scripts)
    import klieg_adapters as A
    import klieg_core as core
    import klieg_bridge as bridge_mod
    import klieg_colour as colour_mod
    import klieg_taste as taste_mod


def _j(obj) -> str:
    return json.dumps(obj, indent=1)


def _frames(spec) -> list[int]:
    if isinstance(spec, list):
        return [int(x) for x in spec]
    out: list[int] = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


# ------------------------------------------------------------------ handlers
def h_probe(args: dict) -> str:
    return _j({"adapters": A.probe_all()})


def _script_error(path: str) -> dict | None:
    if not path:
        return {"error": "script is required"}
    if not os.path.exists(path):
        return {"error": f"script does not exist: {path}"}
    if not os.path.isfile(path):
        return {"error": f"script is not a file: {path}"}
    return None


def h_run(args: dict) -> str:
    dcc = args.get("dcc", "blender")
    err = _script_error(args.get("script", ""))
    if err:
        return _j(err)
    ad = A.get(dcc)
    info = ad.detect()
    if not info.get("found"):
        return _j({"error": f"{dcc} not found on PATH", "probe": info})
    blend = args.get("blend")
    if blend and not os.path.exists(blend):
        return _j({"error": f"blend does not exist: {blend}"})
    argv = ad.run_argv(args["script"], blend=args.get("blend"), args=args.get("args"))
    if argv is None:
        return _j({"error": f"{dcc} cannot be driven headlessly in 0.1"})
    if args.get("bg"):
        return _j(core.launch(args.get("name", "run"), argv, guard=args.get("guard") or [],
                              env=A.SAFE_ENV, dcc=dcc, what=args.get("script", "")))
    p = core.run_child(argv, timeout=args.get("timeout", 600), cwd=os.getcwd(),
                       extra_env=A.SAFE_ENV)
    return _j({"exit": p.returncode,
               "stdout_tail": "\n".join((p.stdout or "").splitlines()[-40:]),
               "stderr_tail": "\n".join((p.stderr or "").splitlines()[-20:])})


def h_render(args: dict) -> str:
    dcc = args.get("dcc", "blender")
    ad = A.get(dcc)
    if not ad.detect().get("found"):
        return _j({"error": f"{dcc} not found"})
    held = core.gpu_busy(dcc)
    if held:
        return _j({"error": "one GPU, one render: another job holds the lock",
                   "held_by": held})
    frames = _frames(args["frames"])
    outdir = os.path.abspath(args["outdir"])
    argv = ad.render_argv(frames, outdir, int(args.get("samples", 128)),
                          int(args.get("pct", 100)), args["blend"], args.get("tag", ""))
    guard = args.get("guard") or [
        os.path.join(outdir, "%04d.png" % frames[0]),
        os.path.join(outdir, "%04d.png" % frames[-1])]
    return _j(core.launch(args.get("name", "render"), argv, guard=guard,
                          env=A.SAFE_ENV, dcc=dcc,
                          what=f"{len(frames)} frames -> {outdir}",
                          expect={"dir": outdir, "min": len(frames), "ext": ".png"},
                          frames=len(frames),
                          queue=bool(args.get("queue", True))))


def h_plan(args: dict) -> str:
    """Resolve a render without running it: the argv, the files it must produce,
    the predicted duration, and every reason it would fail.

    This exists because a wrong render costs an hour and a weak model will happily
    start one. Plan is free; the answer is checkable before the GPU is touched.
    """
    dcc = args.get("dcc", "blender")
    blockers, warnings = [], []
    try:
        ad = A.get(dcc)
    except KeyError as e:
        return _j({"error": str(e), "blockers": ["unknown dcc"]})
    info = ad.detect()
    if not info.get("found"):
        blockers.append(f"{dcc} not found on PATH")

    blend = args.get("blend")
    if not blend:
        blockers.append("blend is required")
    elif not os.path.exists(blend):
        blockers.append(f"blend does not exist: {blend}")

    try:
        frames = _frames(args.get("frames", ""))
    except ValueError:
        frames, _ = [], blockers.append("frames spec did not parse")
    if not frames:
        blockers.append("frames is empty")

    outdir = os.path.abspath(args.get("outdir", "")) if args.get("outdir") else ""
    if not outdir:
        blockers.append("outdir is required")
    else:
        parent = os.path.dirname(outdir) or "."
        if not os.path.isdir(parent):
            warnings.append(f"parent dir will be created: {parent}")
        if os.path.isdir(outdir) and os.listdir(outdir):
            warnings.append(f"outdir is not empty ({len(os.listdir(outdir))} entries); "
                            "old frames can mimic a finished render")

    samples = int(args.get("samples", 128))
    pct = int(args.get("pct", 100))
    if pct < 1 or pct > 100:
        blockers.append("pct must be 1..100")
    if samples < 1:
        blockers.append("samples must be >= 1")

    held = core.gpu_busy(dcc) if info.get("found") else None
    if held:
        warnings.append(f"{dcc} busy with {held.get('job')} - this render would queue")

    argv = ad.render_argv(frames, outdir, samples, pct, blend or "<blend>") if info.get("found") else []
    if argv:
        argv = [("<generated render script>" if a.endswith("_klieg_render.py") else a) for a in argv]

    plan = {
        "dcc": dcc, "version": info.get("version"),
        "argv": argv,
        "frame_count": len(frames),
        "expected_first": os.path.join(outdir, "%04d.png" % frames[0]) if frames and outdir else None,
        "expected_last": os.path.join(outdir, "%04d.png" % frames[-1]) if frames and outdir else None,
        "predicted_seconds": core.predict(dcc, len(frames)),
        "blockers": blockers,
        "warnings": warnings,
        "would_run": not blockers,
    }
    return _j(plan)


def h_jobs(args: dict) -> str:
    action = args.get("action", "list")
    job = args.get("job", "")
    if action == "list":
        return _j({"jobs": core.list_jobs(int(args.get("limit", 20)))})
    if action == "queue":
        started = core.dispatch()
        return _j({"started": started,
                   "queued": [j for j in core.list_jobs(50) if j.get("state") == "queued"]})
    if not job:
        return _j({"error": "action requires 'job'"})
    if action == "status":
        return _j(core.poll(job))
    if action == "log":
        return _j({"job": job, "log": core.tail(job, int(args.get("lines", 40)))})
    if action == "verify":
        return _j(core.verify(job))
    if action == "kill":
        return _j(core.kill(job))
    return _j({"error": f"unknown action {action}"})


SCENE_SCRIPT = '''\
import bpy, json
sc = bpy.context.scene
objs = [{"name": o.name, "type": o.type,
         "verts": len(o.data.vertices) if o.type == "MESH" else 0}
        for o in sc.objects]
print("KLIIEG_SCENE", json.dumps({
    "file": bpy.data.filepath,
    "engine": sc.render.engine,
    "resolution": [sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage],
    "frames": [sc.frame_start, sc.frame_end, sc.render.fps],
    "view_transform": sc.view_settings.view_transform,
    "objects": objs,
    "total_verts": sum(o["verts"] for o in objs),
}), flush=True)
'''


def h_scene(args: dict) -> str:
    dcc = args.get("dcc", "blender")
    ad = A.get(dcc)
    if dcc != "blender":
        return _j({"error": f"scene inspection for {dcc} lands in 0.2"})
    script = os.path.join(core.data_dir(), "_klieg_scene.py")
    with open(script, "w") as f:
        f.write(SCENE_SCRIPT)
    argv = ad.run_argv(script, blend=args.get("blend"))
    p = core.run_child(argv, timeout=300, extra_env=A.SAFE_ENV)
    for line in (p.stdout or "").splitlines():
        if line.startswith("KLIIEG_SCENE "):
            return line.split(" ", 1)[1]
    return _j({"error": "no scene block in output", "stderr": (p.stderr or "")[-800:]})


def h_track(args: dict) -> str:
    """Run a projection script and hand back the JSON it writes."""
    dcc = args.get("dcc", "blender")
    ad = A.get(dcc)
    argv = ad.run_argv(args["script"], blend=args.get("blend"),
                       args=[args["out"]] if args.get("out") else None)
    if argv is None:
        return _j({"error": f"{dcc} cannot be driven headlessly in 0.1"})
    p = core.run_child(argv, timeout=args.get("timeout", 1800), extra_env=A.SAFE_ENV)
    out = args.get("out")
    res = {"exit": p.returncode,
           "stdout_tail": "\n".join((p.stdout or "").splitlines()[-20:])}
    if out and os.path.exists(out):
        res["written"] = out
        res["bytes"] = os.path.getsize(out)
    else:
        res["error"] = "expected output not written"
    return _j(res)


def h_gate(args: dict) -> str:
    """Run a measurement script and return the JSON block it prints.

    A gate is a number, not a feeling: the script must print `KLIIEG_GATE {json}`.
    """
    dcc = args.get("dcc", "blender")
    ad = A.get(dcc)
    argv = ad.run_argv(args["script"], blend=args.get("blend"),
                       args=[json.dumps(args.get("params") or {})])
    if argv is None:
        return _j({"error": f"{dcc} cannot be driven headlessly in 0.1"})
    p = core.run_child(argv, timeout=args.get("timeout", 1800), extra_env=A.SAFE_ENV)
    for line in (p.stdout or "").splitlines():
        if line.startswith("KLIIEG_GATE "):
            try:
                return _j({"job_exit": p.returncode,
                           "gate": json.loads(line.split(" ", 1)[1])})
            except json.JSONDecodeError as e:
                return _j({"error": f"gate block not JSON: {e}"})
    return _j({"error": "no KLIIEG_GATE block", "exit": p.returncode,
               "stderr": (p.stderr or "")[-600:]})


FORBIDDEN_WRITE = ("/etc", "/usr", "/bin", "/sbin", "/boot", "/dev", "/proc", "/sys",
                   "/lib", "/opt", "/var/lib")
# A deny-list, not a read: these are paths Klieg refuses to write into. Listed here so a
# reviewer can see the boundary, and so the refusal message can name the rule.
FORBIDDEN_HOME = ("~/.ssh", "~/.aws", "~/.gnupg", "~/.config/hermes", "~/.hermes")


def _write_allowed(path: str) -> str | None:
    """Return a refusal reason, or None when the path is acceptable.

    An encoder is not a privilege boundary, but writing a deliverable into /etc or
    ~/.ssh is never what a user meant, and a model mistyping a path should be
    corrected rather than obeyed.
    """
    ap = os.path.abspath(os.path.expanduser(path))
    for bad in FORBIDDEN_WRITE:
        if ap == bad or ap.startswith(bad + os.sep):
            return f"refusing to write under {bad}"
    for bad in FORBIDDEN_HOME:
        b = os.path.abspath(os.path.expanduser(bad))
        if ap == b or ap.startswith(b + os.sep):
            return f"refusing to write under {bad}"
    return None


def h_publish(args: dict) -> str:
    """Encode with explicit BT.709 and the tags in the stream, or phones shift gamma."""
    frames = os.path.abspath(args["frames_dir"])
    out = os.path.abspath(args["out"])
    refusal = _write_allowed(out)
    if refusal:
        return _j({"error": refusal, "out": out})
    if not os.path.isdir(frames):
        return _j({"error": f"frames_dir does not exist: {frames}"})
    if not any(n.endswith(".png") for n in os.listdir(frames)):
        return _j({"error": f"no PNG frames in {frames}"})
    audio = args.get("audio")
    if audio and not os.path.exists(audio):
        return _j({"error": f"audio does not exist: {audio}"})
    fps = str(args.get("fps", 30))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    scale = ("scale=in_color_matrix=bt709:out_color_matrix=bt709:out_range=tv,"
             # libx264 + yuv420p needs even dimensions; a 25 % render is often odd,
             # and "width not divisible by 2" is not a helpful thing to hand a user
             "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p")
    tags = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            "-color_range", "tv",
            "-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1"]
    argv = ["ffmpeg", "-y", "-framerate", fps, "-i", os.path.join(frames, "%04d.png")]
    if audio:
        argv += ["-i", audio, "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-shortest"]
    argv += ["-vf", scale, "-c:v", "libx264", "-preset", "slow", "-profile:v", "high"]
    if args.get("crf"):
        argv += ["-crf", str(args["crf"])]
    else:
        argv += ["-b:v", args.get("bitrate", "16M")]
    argv += tags + [out]
    return _j(core.launch(args.get("name", "publish"), argv, guard=[out],
                          what=f"encode -> {out}"))


# ------------------------------------------------------------------ live session
def _sessions() -> dict:
    p = os.path.join(core.data_dir(), "sessions.json")
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_sessions(d: dict) -> None:
    with open(os.path.join(core.data_dir(), "sessions.json"), "w") as f:
        json.dump(d, f, indent=1)


def h_session(args: dict) -> str:
    action = args.get("action", "status")
    sock = args.get("socket") or ""
    sessions = _sessions()

    if action == "start":
        dcc = args.get("dcc", "blender")
        ad = A.get(dcc)
        if not ad.detect().get("found"):
            return _j({"error": f"{dcc} not found"})
        if dcc != "blender":
            return _j({"error": f"live bridge for {dcc} lands in a later adapter; Blender works today"})
        sid = os.urandom(4).hex()
        sock = os.path.join(core.data_dir(), f"live-{sid}.sock")
        server = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "blender/klieg_headless_server.py")
        argv = [ad.find_binary(), "-b"]
        if args.get("blend"):
            argv.append(args["blend"])
        argv += ["--python", server, "--", sock]
        job = core.launch("live", argv, guard=[sock], env=A.SAFE_ENV, dcc=dcc,
                          what=f"live bridge -> {sock}", queue=False)
        if job.get("state") == "refused":
            return _j(job)
        deadline = time.time() + float(args.get("wait", 90))
        while time.time() < deadline and not os.path.exists(sock):
            time.sleep(0.3)
        ok = os.path.exists(sock)
        sessions[sock] = {"job": job["job"], "dcc": dcc, "blend": args.get("blend")}
        _save_sessions(sessions)
        return _j({"socket": sock, "job": job["job"], "bound": ok,
                   "note": "eval is approval-gated; the bridge executes on Blender's main thread"})

    if action == "list":
        return _j({"sessions": [{"socket": k, **v} for k, v in sessions.items()]})

    if not sock:
        socks = list(sessions)
        if len(socks) == 1:
            sock = socks[0]
        else:
            return _j({"error": "socket is required when more than one session exists",
                       "sockets": socks})

    br = bridge_mod.Bridge(sock, timeout=float(args.get("timeout", 20)))
    try:
        if action == "status":
            info = br.info()
            return _j({"socket": sock, "ok": info.get("ok"), "info": info.get("result")})
        if action == "eval":
            r = br.eval(code=args.get("code", ""), expr=args.get("expr", "None"))
            return _j({"socket": sock, **r})
        if action == "colour":
            return _j({"socket": sock, "colour": colour_mod.probe_session(br)})
        if action == "stop":
            r = br.shutdown()
            sessions.pop(sock, None)
            _save_sessions(sessions)
            return _j({"socket": sock, **r})
        return _j({"error": f"unknown action {action}"})
    except bridge_mod.BridgeUnavailable as e:
        return _j({"error": "host not reachable", "detail": str(e),
                   "hint": "the live session is not running; start one or use batch"})
    except bridge_mod.BridgeTimeout as e:
        return _j({"error": "host busy", "detail": str(e),
                   "hint": "Blender is modal or mid-operation; it is alive, retry later"})


# ------------------------------------------------------------------ colour
def h_colour(args: dict) -> str:
    action = args.get("action", "probe")
    dcc = args.get("dcc", "blender")
    if action in ("probe", "write", "compare"):
        blend = args.get("blend")
        if action != "probe" and not blend:
            return _j({"error": "blend is required"})
        ad = A.get(dcc)
        if not ad.detect().get("found"):
            return _j({"error": f"{dcc} not found"})
        sock = args.get("socket")
        if sock:
            m = colour_mod.probe_session(bridge_mod.Bridge(sock))
        else:
            if not blend or not os.path.exists(blend):
                return _j({"error": f"blend does not exist: {blend}"})
            m = colour_mod.probe_batch(ad.find_binary(), blend)
        if action == "probe":
            return _j({"colour": colour_mod.stamp(m)})
        if action == "write":
            p = colour_mod.write(args.get("into") or os.path.dirname(blend), m)
            return _j({"written": p, "manifest": colour_mod.stamp(m)})
        expected = colour_mod.read(args.get("into") or os.path.dirname(blend))
        if not expected:
            return _j({"error": "no colour_manifest.json to compare against"})
        diffs = colour_mod.compare(expected, m)
        return _j({"fields_diff": diffs, "same_film": not diffs,
                   "note": "a changed view_transform means the frames are not the same film"})
    if action == "tags":
        path = args.get("file")
        if not path or not os.path.exists(path):
            return _j({"error": f"file does not exist: {path}"})
        ok, tags = colour_mod.tags_ok(path)
        return _j({"bt709": ok, "tags": tags})
    return _j({"error": f"unknown action {action}"})


# ------------------------------------------------------------------ taste
def h_taste(args: dict) -> str:
    """Taste verbs need numpy/Pillow; report a missing dep as data, never a trace."""
    action = args.get("action", "list")
    pixel_actions = {"features", "record", "train", "score"}
    if action in pixel_actions:
        try:
            taste_mod._deps()
        except ImportError as e:
            return _j({"error": f"optional dependency missing: {e}",
                       "hint": "install numpy and Pillow to use klieg_taste pixel verbs"})
    if action == "features":
        path = args.get("frame")
        if not path or not os.path.exists(path):
            return _j({"error": f"frame does not exist: {path}"})
        return _j({"frame": path, "features": taste_mod.features(path)})
    if action == "record":
        path = args.get("frame")
        if not path or not os.path.exists(path):
            return _j({"error": f"frame does not exist: {path}"})
        return _j(taste_mod.record(path, bool(args.get("accepted")),
                                   args.get("reason", ""), args.get("tags", [])))
    if action == "train":
        return _j(taste_mod.train())
    if action == "score":
        path = args.get("frame")
        if not path or not os.path.exists(path):
            return _j({"error": f"frame does not exist: {path}"})
        return _j(taste_mod.score(path))
    rows = taste_mod.load()
    return _j({"verdicts": len(rows),
               "accepted": sum(1 for r in rows if r["accepted"]),
               "need": taste_mod.MIN_SAMPLES,
               "recent": [{"path": os.path.basename(r["path"]), "accepted": r["accepted"],
                           "reason": r["reason"]} for r in rows[-5:]]})


# ------------------------------------------------------------------ specs
def _schema(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


TOOL_SPECS = [
    dict(name="klieg_probe", handler=h_probe, emoji="🔎",
         description="List motion/design hosts installed on this machine (Blender, Houdini, Nuke, C4D, AE, Resolve) with versions.",
         schema=_schema({})),
    dict(name="klieg_run", handler=h_run, emoji="🎛️",
         description="Run a Python script inside a DCC. bg=true detaches it with a logfile and exit code instead of blocking.",
         schema=_schema({"dcc": {"type": "string"}, "script": {"type": "string"},
                         "blend": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}},
                         "bg": {"type": "boolean"}, "name": {"type": "string"},
                         "timeout": {"type": "integer"}}, ["script"])),
    dict(name="klieg_render", handler=h_render, emoji="🎬",
         description="Render a frame range as a detached resumable job, with a GPU lock and artefact guards.",
         schema=_schema({"dcc": {"type": "string"}, "blend": {"type": "string"},
                         "frames": {"type": "string", "description": "e.g. '0-143' or '0,110,230'"},
                         "outdir": {"type": "string"}, "samples": {"type": "integer"},
                         "pct": {"type": "integer"}, "guard": {"type": "array", "items": {"type": "string"}},
                         "queue": {"type": "boolean", "description": "queue behind the GPU holder instead of refusing (default true)"},
                         "name": {"type": "string"}}, ["blend", "frames", "outdir"])),
    dict(name="klieg_plan", handler=h_plan, emoji="🧭",
         description="Resolve a render without running it: exact argv, expected files, predicted duration, blockers.",
         schema=_schema({"dcc": {"type": "string"}, "blend": {"type": "string"},
                         "frames": {"type": "string"}, "outdir": {"type": "string"},
                         "samples": {"type": "integer"}, "pct": {"type": "integer"}})),
    dict(name="klieg_jobs", handler=h_jobs, emoji="📋",
         description="Inspect jobs: list, queue (advance it), status, log, verify (artefacts exist AND are newer than the job), kill.",
         schema=_schema({"action": {"type": "string", "enum": ["list", "queue", "status", "log", "verify", "kill"]},
                         "job": {"type": "string"}, "lines": {"type": "integer"},
                         "limit": {"type": "integer"}})),
    dict(name="klieg_scene", handler=h_scene, emoji="🧾",
         description="Inspect a scene: engine, resolution, frame range, view transform, objects and vertex totals.",
         schema=_schema({"dcc": {"type": "string"}, "blend": {"type": "string"}})),
    dict(name="klieg_track", handler=h_track, emoji="📐",
         description="Run a projection/tracking script and confirm the JSON it was supposed to write.",
         schema=_schema({"dcc": {"type": "string"}, "script": {"type": "string"},
                         "blend": {"type": "string"}, "out": {"type": "string"},
                         "timeout": {"type": "integer"}}, ["script"])),
    dict(name="klieg_gate", handler=h_gate, emoji="⚖️",
         description="Run a measurement script; it must print KLIIEG_GATE {json}. Returns the numbers, not a verdict.",
         schema=_schema({"dcc": {"type": "string"}, "script": {"type": "string"},
                         "blend": {"type": "string"}, "params": {"type": "object"},
                         "timeout": {"type": "integer"}}, ["script"])),
    dict(name="klieg_publish", handler=h_publish, emoji="📦",
         description="Encode frames to MP4 with explicit BT.709 conversion and colour tags in the bitstream.",
         schema=_schema({"frames_dir": {"type": "string"}, "out": {"type": "string"},
                         "audio": {"type": "string"}, "fps": {"type": "integer"},
                         "crf": {"type": "integer"}, "bitrate": {"type": "string"},
                         "name": {"type": "string"}}, ["frames_dir", "out"])),
    dict(name="klieg_session", handler=h_session, emoji="🔌",
         description="Live bridge to a running Blender: start a headless host, eval code, read colour state, stop. Distinguishes 'busy' from 'dead'.",
         schema=_schema({"action": {"type": "string",
                                    "enum": ["start", "status", "eval", "colour", "stop", "list"]},
                         "dcc": {"type": "string"}, "blend": {"type": "string"},
                         "socket": {"type": "string"}, "code": {"type": "string"},
                         "expr": {"type": "string"}, "wait": {"type": "integer"},
                         "timeout": {"type": "integer"}}, ["action"])),
    dict(name="klieg_colour", handler=h_colour, emoji="🎨",
         description="Colour management beyond tags: probe display/view transform/look/exposure, write a manifest with the OCIO config hash, diff it, verify BT.709 tags in a file.",
         schema=_schema({"action": {"type": "string", "enum": ["probe", "write", "compare", "tags"]},
                         "dcc": {"type": "string"}, "blend": {"type": "string"},
                         "into": {"type": "string"}, "socket": {"type": "string"},
                         "file": {"type": "string"}}, ["action"])),
    dict(name="klieg_taste", handler=h_taste, emoji="🧪",
         description="Taste learned from your verdicts: record accept/reject on frames, train, then score a new frame with the features that moved it. Refuses to score below 12 verdicts.",
         schema=_schema({"action": {"type": "string", "enum": ["features", "record", "train", "score", "list"]},
                         "frame": {"type": "string"}, "accepted": {"type": "boolean"},
                         "reason": {"type": "string"},
                         "tags": {"type": "array", "items": {"type": "string"}}}, ["action"])),
]
