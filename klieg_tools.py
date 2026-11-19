"""The tool surface: eight verbs that cover a shot, not eighty that cover a UI."""

from __future__ import annotations

import functools
import json
import os
import re
import subprocess
import sys
import time

try:  # loaded as a Hermes plugin package
    from . import klieg_adapters as A
    from . import klieg_core as core
    from . import klieg_bridge as bridge_mod
    from . import klieg_colour as colour_mod
    from . import klieg_taste as taste_mod
    from . import klieg_ledger as ledger_mod
    from . import klieg_gates as gates_mod
    from . import klieg_motion as motion_mod
except ImportError:  # loaded standalone (tests, scripts)
    import klieg_adapters as A
    import klieg_core as core
    import klieg_bridge as bridge_mod
    import klieg_colour as colour_mod
    import klieg_taste as taste_mod
    import klieg_ledger as ledger_mod
    import klieg_gates as gates_mod
    import klieg_motion as motion_mod


def _j(obj) -> str:
    return json.dumps(obj, indent=1)


class _InputError(Exception):
    """Bad input that must reach the model as a JSON error, never a traceback."""

    def __init__(self, payload: dict):
        super().__init__(payload.get("error", "bad input"))
        self.payload = payload


def _handler(fn):
    """Turn input errors and host timeouts into data.

    Every verb is wrapped: a mistyped argument is a correction the model can
    make, and a stack trace is not. TimeoutExpired carries its own timeout, so
    the hint stays accurate without per-handler bookkeeping.
    """
    @functools.wraps(fn)
    def wrap(args: dict) -> str:
        try:
            return fn(args or {})
        except _InputError as e:
            return _j(e.payload)
        except subprocess.TimeoutExpired as e:
            return _j(_timeout_result(e.timeout))
    return wrap


def _get_adapter(dcc: str):
    """The adapter, or a structured unknown-host error. Never a KeyError."""
    try:
        return A.get(dcc)
    except KeyError as e:
        raise _InputError({"error": str(e)}) from e


def _int_arg(args: dict, key: str, default: int, lo: int | None = None, hi: int | None = None) -> int:
    """A validated integer, or a structured error. Never a ValueError."""
    raw = args.get(key, default)
    try:
        v = int(raw)
    except (TypeError, ValueError):
        raise _InputError({"error": f"{key} must be an integer, got {raw!r}"})
    if lo is not None and v < lo:
        raise _InputError({"error": f"{key} must be >= {lo}, got {v}"})
    if hi is not None and v > hi:
        raise _InputError({"error": f"{key} must be <= {hi}, got {v}"})
    return v


def _timeout_result(seconds) -> dict:
    return {"error": f"timed out after {seconds}s",
            "hint": "the host is slow or stuck; for long work use bg=true (klieg_run) "
                    "or raise timeout, and check the job log"}


def resolve_write_path(path) -> str:
    """Absolute, ~-expanded form of a write destination.

    The approval hook and the handlers share this one resolver so the prompt
    names exactly the path the tool will write - a raw or relative string in
    the prompt is how a user approves one destination and gets another.
    """
    return os.path.abspath(os.path.expanduser(str(path)))


_FRAME_PART = re.compile(r"^\d+$")
_FRAME_RANGE = re.compile(r"^(\d+)-(\d+)$")
MAX_FRAMES = 100_000  # a weak model typing 0-999999999 must not allocate a billion ints


def parse_frames(spec) -> tuple[list[int], str | None]:
    """Strictly parse N, A-B, or comma lists. Returns (frames, error)."""
    if isinstance(spec, list):
        out = []
        for x in spec:
            if not _FRAME_PART.fullmatch(str(x).strip()):
                return [], f"invalid frame: {x!r}"
            out.append(int(x))
            if len(out) > MAX_FRAMES:
                return [], f"frame list exceeds {MAX_FRAMES} frames"
        return out, None
    text = str(spec or "").strip()
    if not text:
        return [], None
    out: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            return [], "empty frame in list"
        m = _FRAME_RANGE.fullmatch(part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if b < a:
                return [], f"reversed frame range: {part}"
            if b - a + 1 > MAX_FRAMES:
                return [], f"range {part} exceeds {MAX_FRAMES} frames"
            out += list(range(a, b + 1))
            continue
        if _FRAME_PART.fullmatch(part):
            out.append(int(part))
            continue
        return [], f"invalid frame spec: {part!r}"
    if len(out) > MAX_FRAMES:
        return [], f"frame spec exceeds {MAX_FRAMES} frames"
    return out, None


def _frames(spec) -> list[int]:
    """Compatibility wrapper: raises ValueError for invalid input."""
    frames, err = parse_frames(spec)
    if err:
        raise ValueError(err)
    return frames


# ------------------------------------------------------------------ handlers
@_handler
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


@_handler
def h_run(args: dict) -> str:
    dcc = args.get("dcc", "blender")
    err = _script_error(args.get("script", ""))
    if err:
        return _j(err)
    ad = _get_adapter(dcc)
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
                              env=A.SAFE_ENV, dcc=dcc, what=args.get("script", ""),
                              meta={"script": os.path.abspath(args["script"])}))
    timeout = _int_arg(args, "timeout", 600, lo=1)
    p = core.run_child(argv, timeout=timeout, cwd=os.getcwd(), extra_env=A.SAFE_ENV)
    return _j({"exit": p.returncode,
               "stdout_tail": "\n".join((p.stdout or "").splitlines()[-40:]),
               "stderr_tail": "\n".join((p.stderr or "").splitlines()[-20:])})


@_handler
def h_render(args: dict) -> str:
    dcc = args.get("dcc", "blender")
    # Validate input before probing the environment: a bad-input error must win
    # on every host, even one without the DCC installed.
    frames, ferr = parse_frames(args.get("frames"))
    if ferr or not frames:
        return _j({"ok": False, "error": ferr or "frames is empty"})
    blend = args.get("blend")
    if not blend:
        return _j({"error": "blend is required"})
    if not os.path.exists(blend):
        return _j({"error": f"blend does not exist: {blend}"})
    if not args.get("outdir"):
        return _j({"error": "outdir is required"})
    samples = _int_arg(args, "samples", 128, lo=1)
    pct = _int_arg(args, "pct", 100, lo=1, hi=100)
    ad = _get_adapter(dcc)
    if not ad.detect().get("found"):
        return _j({"error": f"{dcc} not found"})
    # No early refusal here: the queue decision belongs to core.launch, which
    # parks the job behind the holder (queue=True) or refuses it (queue=False).
    # Refusing here made the engine's queue unreachable from the tool.
    outdir = resolve_write_path(args["outdir"])
    refusal = _write_allowed(outdir)
    if refusal:
        return _j({"error": refusal, "outdir": outdir})
    try:
        argv = ad.render_argv(frames, outdir, samples, pct, blend, args.get("tag", ""))
    except NotImplementedError:
        return _j({"error": f"{dcc} renders are not supported by this adapter yet; "
                            "klieg_run can drive its script CLI"})
    guard = args.get("guard") or [
        os.path.join(outdir, "%04d.png" % frames[0]),
        os.path.join(outdir, "%04d.png" % frames[-1])]
    return _j(core.launch(args.get("name", "render"), argv, guard=guard,
                          env=A.SAFE_ENV, dcc=dcc,
                          what=f"{len(frames)} frames -> {outdir}",
                          expect={"dir": outdir, "min": len(frames), "ext": ".png"},
                          frames=len(frames),
                          queue=bool(args.get("queue", True)),
                          meta={"blend": os.path.abspath(blend)}))


@_handler
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

    frames, ferr = parse_frames(args.get("frames", ""))
    if ferr:
        blockers.append(f"frames: {ferr}")
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

    try:
        samples = _int_arg(args, "samples", 128, lo=1)
    except _InputError as e:
        blockers.append(e.payload["error"])
        samples = 128
    try:
        pct = _int_arg(args, "pct", 100, lo=1, hi=100)
    except _InputError as e:
        blockers.append(e.payload["error"])
        pct = 100

    held = core.gpu_busy(dcc) if info.get("found") else None
    if held:
        warnings.append(f"{dcc} busy with {held.get('job')} - this render would queue")

    argv = []
    if info.get("found") and outdir and frames:
        try:
            argv = ad.render_argv(frames, outdir, samples, pct, blend or "<blend>", dry=True)
        except NotImplementedError:
            blockers.append(f"{dcc} renders are not supported by this adapter yet")
    if argv:
        argv = [("<generated render script>" if "_klieg_render" in a else a) for a in argv]

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


@_handler
def h_jobs(args: dict) -> str:
    action = args.get("action", "list")
    job = args.get("job", "")
    if action == "list":
        limit = _int_arg(args, "limit", 20, lo=1, hi=500)
        return _j({"jobs": core.list_jobs(limit)})
    if action == "queue":
        started = core.dispatch()
        return _j({"started": started,
                   "queued": [j for j in core.list_jobs(50) if j.get("state") == "queued"]})
    if not job:
        return _j({"error": "action requires 'job'"})
    if not core.valid_job_id(job):
        return _j({"ok": False, "error": f"invalid job id: {job!r}"})
    if action == "status":
        return _j(core.poll(job))
    if action == "log":
        lines = _int_arg(args, "lines", 40, lo=1, hi=2000)
        return _j({"job": job, "log": core.tail(job, lines)})
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


@_handler
def h_scene(args: dict) -> str:
    dcc = args.get("dcc", "blender")
    ad = _get_adapter(dcc)
    if dcc != "blender":
        return _j({"error": f"scene inspection for {dcc} lands in 0.2"})
    blend = args.get("blend")
    if blend and not os.path.exists(blend):
        return _j({"error": f"blend does not exist: {blend}"})
    script = os.path.join(core.data_dir(), "_klieg_scene.py")
    with open(script, "w") as f:
        f.write(SCENE_SCRIPT)
    argv = ad.run_argv(script, blend=blend)
    p = core.run_child(argv, timeout=300, extra_env=A.SAFE_ENV)
    for line in (p.stdout or "").splitlines():
        if line.startswith("KLIIEG_SCENE "):
            return line.split(" ", 1)[1]
    return _j({"error": "no scene block in output", "stderr": (p.stderr or "")[-800:]})


@_handler
def h_track(args: dict) -> str:
    """Run a projection script and hand back the JSON it writes."""
    dcc = args.get("dcc", "blender")
    err = _script_error(args.get("script", ""))
    if err:
        return _j(err)
    ad = _get_adapter(dcc)
    blend = args.get("blend")
    if blend and not os.path.exists(blend):
        return _j({"error": f"blend does not exist: {blend}"})
    argv = ad.run_argv(args["script"], blend=blend,
                       args=[resolve_write_path(args["out"])] if args.get("out") else None)
    if argv is None:
        return _j({"error": f"{dcc} cannot be driven headlessly in 0.1"})
    timeout = _int_arg(args, "timeout", 1800, lo=1)
    p = core.run_child(argv, timeout=timeout, extra_env=A.SAFE_ENV)
    out = resolve_write_path(args["out"]) if args.get("out") else None
    res = {"exit": p.returncode,
           "stdout_tail": "\n".join((p.stdout or "").splitlines()[-20:])}
    if out and os.path.exists(out):
        res["written"] = out
        res["bytes"] = os.path.getsize(out)
    else:
        res["error"] = "expected output not written"
    return _j(res)


@_handler
def h_gate(args: dict) -> str:
    """Run a measurement and return numbers, not a feeling.

    Two paths: a built-in gate (flash/loop/stats/safe_band) measured directly
    over a frame directory with numpy/Pillow - no DCC, no model-authored code -
    or a script inside a DCC that must print `KLIIEG_GATE {json}`.
    """
    gate = args.get("gate")
    if gate:
        if args.get("script"):
            return _j({"error": "give gate or script, not both"})
        frames_dir = args.get("frames_dir")
        if not frames_dir or not os.path.isdir(frames_dir):
            return _j({"error": f"frames_dir does not exist: {frames_dir}"})
        fps = _int_arg(args, "fps", 30, lo=1, hi=240)
        try:
            gates_mod._deps()
        except ImportError as e:
            return _j({"error": f"optional dependency missing: {e}",
                       "hint": "install numpy and Pillow to use built-in gates"})
        return _j(gates_mod.run(gate, os.path.abspath(frames_dir), fps,
                                args.get("params") or {}))
    dcc = args.get("dcc", "blender")
    script = args.get("script") or ""
    resolved = os.path.abspath(os.path.expanduser(script)) if script else ""
    if not script or not os.path.isfile(resolved):
        return _j({"ok": False, "error": f"script not found: {resolved or '<empty>'}"})
    ad = _get_adapter(dcc)
    argv = ad.run_argv(resolved, blend=args.get("blend"),
                       args=[json.dumps(args.get("params") or {})])
    if argv is None:
        return _j({"error": f"{dcc} cannot be driven headlessly in 0.1"})
    timeout = _int_arg(args, "timeout", 1800, lo=1)
    p = core.run_child(argv, timeout=timeout, extra_env=A.SAFE_ENV)
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
# The home inventory mirrors hermes-agent's agent/file_safety.py (HOME_CREDENTIAL_DIRS,
# HOME_CREDENTIAL_FILES, SHELL_RC_FILES) plus autostart and ~/.local/bin: a deliverable
# written into any of these is persistence or credential theft, not output.
FORBIDDEN_HOME = ("~/.ssh", "~/.aws", "~/.gnupg", "~/.kube", "~/.docker", "~/.azure",
                  "~/.config/gh", "~/.config/gcloud", "~/.config/hermes", "~/.hermes",
                  "~/.config/autostart", "~/.local/bin")
FORBIDDEN_HOME_FILES = ("~/.netrc", "~/_netrc", "~/.pgpass", "~/.npmrc", "~/.pypirc",
                        "~/.git-credentials", "~/.bashrc", "~/.zshrc", "~/.profile",
                        "~/.bash_profile", "~/.zprofile")


def _write_allowed(path: str) -> str | None:
    """Return a refusal reason, or None when the path is acceptable.

    An encoder is not a privilege boundary, but writing a deliverable into /etc or
    ~/.ssh is never what a user meant, and a model mistyping a path should be
    corrected rather than obeyed. realpath (not just abspath) so a symlink with
    an innocuous name cannot alias a credential store.
    """
    ap = os.path.realpath(os.path.expanduser(str(path)))
    for bad in FORBIDDEN_WRITE:
        # Resolve the prefix as well as the candidate: on macOS /etc is a symlink to
        # /private/etc, so a literal /etc/... destination resolves to /private/etc/...
        # and must still match the rule. Comparing only the literal prefix let it slip.
        b = os.path.realpath(bad)
        if ap == b or ap.startswith(b + os.sep):
            return f"refusing to write under {bad}"
    for bad in FORBIDDEN_HOME:
        b = os.path.realpath(os.path.expanduser(bad))
        if ap == b or ap.startswith(b + os.sep):
            return f"refusing to write under {bad}"
    for bad in FORBIDDEN_HOME_FILES:
        if ap == os.path.realpath(os.path.expanduser(bad)):
            return f"refusing to write to {bad}"
    return None


_NUM_PNG = re.compile(r"^(\d+)\.png$")


def _frame_sequence(frames_dir: str):
    """The numbered PNGs, in frame order. Returns ((nums, paths, widths), None)
    or (None, error). Non-numbered PNGs cannot be a sequence and are reported."""
    entries = []
    for n in os.listdir(frames_dir):
        m = _NUM_PNG.fullmatch(n)
        if m:
            entries.append((int(m.group(1)), m.group(1), n))
    if not entries:
        return None, f"no numbered PNG frames (NNNN.png) in {frames_dir}"
    entries.sort()
    nums = [i for i, _, _ in entries]
    paths = [os.path.join(frames_dir, n) for _, _, n in entries]
    widths = {len(digits) for _, digits, _ in entries}
    return (nums, paths, widths), None


@_handler
def h_publish(args: dict) -> str:
    """Encode with explicit BT.709 and the tags in the stream, or phones shift gamma."""
    if not args.get("frames_dir"):
        return _j({"error": "frames_dir is required"})
    if not args.get("out"):
        return _j({"error": "out is required"})
    fps = _int_arg(args, "fps", 30, lo=1, hi=240)
    crf = None
    if args.get("crf") is not None:
        crf = _int_arg(args, "crf", 18, lo=0, hi=51)
    frames = os.path.abspath(args["frames_dir"])
    out = os.path.abspath(args["out"])
    refusal = _write_allowed(out)
    if refusal:
        return _j({"error": refusal, "out": out})
    if not os.path.isdir(frames):
        return _j({"error": f"frames_dir does not exist: {frames}"})
    seq, serr = _frame_sequence(frames)
    if seq is None:
        return _j({"error": serr or "no frames"})
    nums, paths, widths = seq
    audio = args.get("audio")
    if audio and not os.path.exists(audio):
        return _j({"error": f"audio does not exist: {audio}"})
    os.makedirs(os.path.dirname(out), exist_ok=True)

    # image2 only probes start numbers 0-4: a mid-sequence render (frames
    # 100-110) failed outright, and a gapped set (0,110,230 - a shape
    # klieg_render explicitly accepts) silently encoded up to the first gap
    # and reported success. Contiguous runs get -start_number; anything else
    # is enumerated frame-by-frame with the concat demuxer.
    contiguous = nums[-1] - nums[0] + 1 == len(nums)
    if contiguous and len(widths) == 1:
        pattern = os.path.join(frames, f"%0{widths.pop()}d.png")
        argv = ["ffmpeg", "-y", "-framerate", str(fps),
                "-start_number", str(nums[0]), "-i", pattern]
    else:
        concat = os.path.join(core.data_dir(), f"publish-{os.urandom(4).hex()}.concat.txt")

        def _esc(p: str) -> str:
            return p.replace("'", "'\\''")

        lines = []
        for p in paths:
            lines.append(f"file '{_esc(p)}'")
            lines.append(f"duration {1.0 / fps:.6f}")
        # No repeated last entry: with image inputs the repeat is an extra
        # decoded frame, not just a duration fix. One file entry = one frame.
        with open(concat, "w") as f:
            f.write("\n".join(lines) + "\n")
        argv = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat]
    if audio:
        argv += ["-i", audio, "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-shortest"]
    scale = ("scale=in_color_matrix=bt709:out_color_matrix=bt709:out_range=tv,"
             # libx264 + yuv420p needs even dimensions; a 25 % render is often odd,
             # and "width not divisible by 2" is not a helpful thing to hand a user
             "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p")
    tags = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            "-color_range", "tv",
            "-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1"]
    argv += ["-vf", scale, "-c:v", "libx264", "-preset", "slow", "-profile:v", "high"]
    if crf is not None:
        argv += ["-crf", str(crf)]
    else:
        argv += ["-b:v", args.get("bitrate", "16M")]
    argv += tags + [out]
    return _j(core.launch(args.get("name", "publish"), argv, guard=[out],
                          what=f"encode {len(nums)} frames -> {out}",
                          meta={"frames_dir": frames, "frame_count": len(nums),
                                "first_frame": nums[0], "last_frame": nums[-1],
                                "gapped": not contiguous}))


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


@_handler
def h_session(args: dict) -> str:
    action = args.get("action", "status")
    sock = args.get("socket") or ""
    sessions = _sessions()

    if action == "start":
        dcc = args.get("dcc", "blender")
        ad = _get_adapter(dcc)
        if not ad.detect().get("found"):
            return _j({"error": f"{dcc} not found"})
        if dcc != "blender":
            return _j({"error": f"live bridge for {dcc} lands in a later adapter; Blender works today"})
        wait = _int_arg(args, "wait", 90, lo=0, hi=600)  # 0 = launch, do not block for the socket
        sid = os.urandom(4).hex()
        sock = os.path.join(core.data_dir(), f"live-{sid}.sock")
        server = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "blender", "klieg_headless_server.py")
        if not os.path.isfile(server):
            return _j({"error": f"bridge server script not found: {server}"})
        argv = [ad.find_binary(), "-b"]
        if args.get("blend"):
            if not os.path.exists(args["blend"]):
                return _j({"error": f"blend does not exist: {args['blend']}"})
            argv.append(args["blend"])
        argv += ["--python", server, "--", sock]
        job = core.launch("live", argv, guard=[sock], env=A.SAFE_ENV, dcc=dcc,
                          what=f"live bridge -> {sock}", queue=False)
        if job.get("state") == "refused":
            return _j(job)
        deadline = time.time() + wait
        while time.time() < deadline and not os.path.exists(sock):
            time.sleep(0.3)
        ok = os.path.exists(sock)
        sessions[sock] = {"job": job["job"], "dcc": dcc, "blend": args.get("blend")}
        _save_sessions(sessions)
        return _j({"socket": sock, "job": job["job"], "bound": ok,
                   "note": "eval is approval-gated; the bridge executes on Blender's main thread"})

    if action == "list":
        # Prune sessions whose host job has exited: a dead Blender must not
        # keep counting toward "more than one session exists" forever.
        live = {}
        for k, v in sessions.items():
            st = core.poll(v["job"]) if v.get("job") else {}
            if st.get("state") in ("done", "failed", "killed"):
                continue
            live[k] = {**v, "job_state": st.get("state", "unknown")}
        if len(live) != len(sessions):
            _save_sessions(live)
        return _j({"sessions": [{"socket": k, **v} for k, v in live.items()]})

    if not sock:
        socks = list(sessions)
        if len(socks) == 1:
            sock = socks[0]
        elif not socks:
            return _j({"error": "no live sessions; start one with action=start",
                       "sessions": []})
        else:
            return _j({"error": "socket is required when more than one session exists",
                       "sockets": socks})

    btimeout = _int_arg(args, "timeout", 20, lo=1, hi=600)
    br = bridge_mod.Bridge(sock, timeout=btimeout)
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
        # The socket is gone. Refresh the job so a dead Blender cannot stay "running".
        entry = sessions.get(sock) or {}
        job_id = entry.get("job")
        state = core.poll(job_id) if job_id else None
        return _j({"error": "host not reachable", "detail": str(e),
                   "job": job_id, "job_state": (state or {}).get("state"),
                   "hint": "the live session is not running; start one or use batch"})
    except bridge_mod.BridgeTimeout as e:
        return _j({"error": "host busy", "detail": str(e),
                   "hint": "Blender is modal or mid-operation; it is alive, retry later"})


# ------------------------------------------------------------------ colour
@_handler
def h_colour(args: dict) -> str:
    action = args.get("action", "probe")
    dcc = args.get("dcc", "blender")
    if action in ("probe", "write", "compare"):
        blend = args.get("blend")
        if action != "probe" and not blend:
            return _j({"error": "blend is required"})
        ad = _get_adapter(dcc)
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
        # A relative blend path ("scene.blend") has dirname "" - resolve before
        # defaulting, and apply the same write boundary publish uses.
        into = os.path.abspath(os.path.expanduser(
            args.get("into") or os.path.dirname(os.path.abspath(blend or "."))))
        if action == "write":
            refusal = _write_allowed(into)
            if refusal:
                return _j({"error": refusal, "into": into})
            p = colour_mod.write(into, m)
            return _j({"written": p, "manifest": colour_mod.stamp(m)})
        expected = colour_mod.read(into)
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
@_handler
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
        if not isinstance(args.get("accepted"), bool):
            return _j({"error": "accepted must be an explicit true/false; "
                                "a missing verdict would silently train the model"})
        return _j(taste_mod.record(path, args["accepted"],
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


# ------------------------------------------------------------------ ledger
@_handler
def h_ledger(args: dict) -> str:
    """Provenance: seal a finished job's inputs and outputs, check for drift."""
    action = args.get("action", "show")
    job = args.get("job", "")
    if not job:
        return _j({"error": "action requires 'job'"})
    if action == "seal":
        return _j(ledger_mod.seal(job))
    if action == "check":
        return _j(ledger_mod.check(job))
    if action == "show":
        return _j(ledger_mod.show(job))
    return _j({"error": f"unknown action {action}"})


# ------------------------------------------------------------------ motion design
def resolve_motion_out(args: dict, mid: str | None = None) -> str:
    """The file klieg_motion will write.

    The approval hook calls this before the handler runs (mid=None): an
    unspecified preview out is named by its default pattern, because the
    random id does not exist yet. render has no default - the handler refuses
    a missing out - so the prompt says so instead of inventing a destination.
    """
    if args.get("out"):
        return resolve_write_path(args["out"])
    if str(args.get("action") or "").lower() == "preview":
        return os.path.join(core.data_dir(), "motion", f"preview-{mid or '<id>'}.png")
    return "<out is required>"


def _motion_scene(args: dict):
    """Resolve a scene to (html, width, height, duration, error)."""
    spec = None
    if args.get("template"):
        try:
            spec = motion_mod.template(args["template"], **(args.get("params") or {}))
        except (ValueError, TypeError) as e:
            return None, 0, 0, 0.0, {"error": str(e)}
    elif args.get("scene"):
        spec = args["scene"]
    if spec is not None:
        try:
            html = motion_mod.compile_scene(spec)
        except (ValueError, TypeError) as e:
            return None, 0, 0, 0.0, {"error": str(e)}
        return (html, int(spec.get("width", 1920)), int(spec.get("height", 1080)),
                float(spec.get("duration", 6)), None)
    if args.get("html"):
        html = args["html"]
    elif args.get("html_path"):
        if not os.path.isfile(args["html_path"]):
            return None, 0, 0, 0.0, {"error": f"html_path not found: {args['html_path']}"}
        with open(args["html_path"]) as f:
            html = f.read()
    else:
        return None, 0, 0, 0.0, {"error": "provide scene, template, html, or html_path"}
    if not args.get("duration"):
        return None, 0, 0, 0.0, {"error": "duration is required for raw html"}
    try:
        dur = float(args["duration"])
    except (TypeError, ValueError):
        return None, 0, 0, 0.0, {"error": "duration must be a number"}
    return html, int(args.get("width", 1920)), int(args.get("height", 1080)), dur, None


@_handler
def h_motion(args: dict) -> str:
    """Author and render 2D motion design: scenes -> MP4/GIF, or preview a frame."""
    action = args.get("action", "templates")
    if action == "templates":
        return _j({"templates": motion_mod.list_templates(),
                   "effects": sorted(motion_mod.EFFECTS),
                   "hint": "action=render with template=<name> + params, or scene=<spec>; "
                           "action=preview renders one frame at t for cheap iteration"})
    if action not in ("render", "preview"):
        return _j({"error": f"unknown action {action}"})
    html, w, h, dur, err = _motion_scene(args)
    if err or html is None:
        return _j(err or {"error": "no scene resolved"})
    w = int(args.get("width", w))
    h = int(args.get("height", h))
    fps = _int_arg(args, "fps", 30, lo=1, hi=60)
    if dur <= 0:
        return _j({"error": "duration must be > 0"})
    mid = os.urandom(4).hex()
    mdir = os.path.join(core.data_dir(), "motion")
    os.makedirs(mdir, exist_ok=True)
    html_path = os.path.join(mdir, f"scene-{mid}.html")
    with open(html_path, "w") as f:
        f.write(html)
    py = os.environ.get("KLIEG_PYTHON") or sys.executable
    engine = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "motion_render.py")

    if action == "preview":
        try:
            t = float(args.get("t", dur / 2))
        except (TypeError, ValueError):
            return _j({"error": "t must be a number"})
        out = resolve_motion_out(args, mid)
        if args.get("out"):
            refusal = _write_allowed(out)
            if refusal:
                return _j({"error": refusal})
        argv = [py, engine, html_path, out, "--preview", str(t), "--width", str(w), "--height", str(h)]
        p = core.run_child(argv, timeout=120)
        if p.returncode != 0:
            return _j({"error": "preview failed", "detail": (p.stderr or p.stdout or "")[-600:],
                       "hint": "needs playwright + chromium-headless-shell in the render interpreter"})
        return _j({"preview": out, "t": t, "width": w, "height": h})

    if not args.get("out"):
        return _j({"error": "out is required"})
    out = resolve_motion_out(args)
    refusal = _write_allowed(out)
    if refusal:
        return _j({"error": refusal, "out": out})
    fmt = args.get("format", "mp4")
    if fmt not in ("mp4", "gif"):
        return _j({"error": "format must be mp4 or gif"})
    argv = [py, engine, html_path, out, "--fps", str(fps), "--duration", str(dur),
            "--width", str(w), "--height", str(h), "--format", fmt]
    if args.get("music"):
        argv += ["--music", args["music"]]
    return _j(core.launch(args.get("name", "motion"), argv, guard=[out],
                          what=f"motion {fmt} {w}x{h} {dur}s -> {out}",
                          meta={"scene_html": html_path, "format": fmt, "duration": dur,
                                "width": w, "height": h, "fps": fps}))


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
         description="Measure, don't trust: built-in gates (flash, loop, stats, safe_band) over a frames_dir with no DCC, or a script in a DCC that prints KLIIEG_GATE {json}. Returns numbers, not verdicts.",
         schema=_schema({"gate": {"type": "string", "enum": ["flash", "loop", "stats", "safe_band"],
                                  "description": "built-in measurement over frames_dir; no script needed"},
                         "frames_dir": {"type": "string"}, "fps": {"type": "integer"},
                         "dcc": {"type": "string"}, "script": {"type": "string"},
                         "blend": {"type": "string"}, "params": {"type": "object"},
                         "timeout": {"type": "integer"}})),
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
    dict(name="klieg_ledger", handler=h_ledger, emoji="🔏",
         description="Provenance for a finished job: seal hashes the scene, frames, colour manifest and encode into a ledger; check re-hashes and reports any drift; show reads the seal.",
         schema=_schema({"action": {"type": "string", "enum": ["seal", "check", "show"]},
                         "job": {"type": "string"}}, ["action", "job"])),
    dict(name="klieg_motion", handler=h_motion, emoji="🎞️",
         description="Author and render 2D motion design. templates lists starters; render turns a scene spec or template (kinetic type, transitions, lower-thirds, logo stings, loops) into MP4/GIF as a detached job; preview renders one frame at t for cheap iteration. Local, no API keys.",
         schema=_schema({"action": {"type": "string", "enum": ["templates", "render", "preview"]},
                         "template": {"type": "string"}, "params": {"type": "object"},
                         "scene": {"type": "object", "description": "declarative layers/keyframes spec"},
                         "html": {"type": "string"}, "html_path": {"type": "string"},
                         "out": {"type": "string"}, "format": {"type": "string", "enum": ["mp4", "gif"]},
                         "fps": {"type": "integer"}, "duration": {"type": "number"},
                         "width": {"type": "integer"}, "height": {"type": "integer"},
                         "t": {"type": "number"}, "music": {"type": "string"}, "name": {"type": "string"}},
                        ["action"])),
]
