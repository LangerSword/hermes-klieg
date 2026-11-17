"""Job engine: detached, logged, resumable work that outlives the agent's shell.

Why this exists: on a laptop with one GPU, a render is 20-70 minutes. Holding an
interactive terminal across it wedges the shell and loses the exit code; a
cron job that reports "ok" is not evidence that frames were written. So every
Klieg job gets its own directory, its own log, a status file written by the
child itself, and an artefact check the caller can run before trusting it.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import time
import uuid

PLUGIN = "klieg"


def data_dir() -> str:
    base = os.environ.get("HERMES_PLUGIN_DATA") or os.path.expanduser("~/.hermes/plugin-data")
    p = os.path.join(base, PLUGIN)
    os.makedirs(p, exist_ok=True)
    return p


def jobs_dir() -> str:
    p = os.path.join(data_dir(), "jobs")
    os.makedirs(p, exist_ok=True)
    return p


def _status_path(job: str) -> str:
    return os.path.join(jobs_dir(), job, "status.json")


def read_status(job: str) -> dict:
    p = _status_path(job)
    if not os.path.exists(p):
        return {"job": job, "state": "unknown"}
    with open(p) as f:
        return json.load(f)


def _write_status(job_id: str, **kw) -> None:
    p = _status_path(job_id)
    cur = read_status(job_id)
    cur.update(kw)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cur, f, indent=1)
    os.replace(tmp, p)


def tail(job: str, lines: int = 40) -> str:
    p = os.path.join(jobs_dir(), job, "log.txt")
    if not os.path.exists(p):
        return ""
    with open(p, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        back = min(size, 64 * 1024)
        f.seek(size - back)
        raw = f.read().decode("utf-8", "replace")
    return "\n".join(raw.splitlines()[-lines:])


# ------------------------------------------------------------------ GPU mutex
def _lock_path(dcc: str) -> str:
    return os.path.join(data_dir(), f"gpu.{dcc}.lock")


def gpu_busy(dcc: str) -> dict | None:
    """One GPU, one render. Returns the holder if someone else holds the lock."""
    p = _lock_path(dcc)
    if not os.path.exists(p):
        return None
    try:
        with open(p) as f:
            info = json.load(f)
        os.kill(int(info.get("pid", 0)), 0)
        return info
    except (ProcessLookupError, ValueError, OSError):
        try:
            os.remove(p)
        except OSError:
            pass
        return None


def _take_lock(dcc: str, job: str, pid: int) -> None:
    with open(_lock_path(dcc), "w") as f:
        json.dump({"pid": pid, "job": job, "dcc": dcc, "since": time.time()}, f)


def release_lock(dcc: str, job: str) -> None:
    p = _lock_path(dcc)
    try:
        with open(p) as f:
            info = json.load(f)
        if info.get("job") == job:
            os.remove(p)
    except OSError:
        pass


# ------------------------------------------------------------------ launch
_LIVE: dict[str, subprocess.Popen] = {}


def _queue_position(job: str) -> int:
    q = [(s.get("created") or 0, n) for n in os.listdir(jobs_dir())
         if (s := read_status(n)).get("state") == "queued"]
    q.sort()
    for i, (_, n) in enumerate(q):
        if n == job:
            return i + 1
    return 0


def _spawn(job: str, name: str, spec: dict, dcc: str, what: str) -> dict:
    """Start an already-created job directory."""
    jd = os.path.join(jobs_dir(), job)
    log = os.path.join(jd, "log.txt")
    child_env = dict(os.environ)
    child_env.update(spec.get("env") or {})
    argv = spec["argv"]

    script = f"{shlex.join(argv)}; echo $? > {shlex.quote(os.path.join(jd, 'exit'))}"
    with open(log, "wb") as fh:
        proc = subprocess.Popen(
            ["/bin/sh", "-c", script],
            stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            cwd=spec.get("cwd") or os.getcwd(), env=child_env,
            start_new_session=True,
        )

    _write_status(job, job=job, name=name, what=what, dcc=dcc, pid=proc.pid,
                  state="running", started=time.time(), log=log,
                  cwd=spec.get("cwd") or os.getcwd(), argv=argv,
                  guard=spec.get("guard") or [], expect=spec.get("expect") or {},
                  frames=spec.get("frames"))
    if dcc:
        _take_lock(dcc, job, proc.pid)
    _LIVE[job] = proc
    return {"job": job, "pid": proc.pid, "log": log, "state": "running"}


def launch(name: str, argv: list[str], cwd: str | None = None,
           env: dict | None = None, guard: list[str] | None = None,
           dcc: str = "", what: str = "", expect: dict | None = None,
           frames: int | None = None, queue: bool = True) -> dict:
    """Launch a job, or queue it behind the current GPU holder.

    A locked GPU used to mean a refusal; a refusal is a bad answer for the second
    thing a user asks for. With queue=True the job is created in the `queued`
    state and starts as soon as the holder exits - advanced by any later poll,
    list or dispatch call, so no daemon is required.
    """
    job = f"{name}-{uuid.uuid4().hex[:8]}"
    spec_env = env or {}

    if dcc and gpu_busy(dcc) and not queue:
        return {"job": job, "state": "refused", "dcc": dcc,
                "error": "one GPU, one render: queue it or wait for the holder",
                "held_by": (gpu_busy(dcc) or {}).get("job")}

    jd = os.path.join(jobs_dir(), job)
    os.makedirs(jd, exist_ok=True)
    spec = dict(argv=argv, cwd=cwd or os.getcwd(), env=spec_env,
                guard=guard or [], expect=expect or {}, frames=frames)

    if dcc and queue and gpu_busy(dcc):
        _write_status(job, job=job, name=name, what=what, dcc=dcc, state="queued",
                      created=time.time(), started=None, spec=spec,
                      guard=guard or [], expect=expect or {}, frames=frames)
        return {"job": job, "state": "queued", "dcc": dcc,
                "position": _queue_position(job),
                "held_by": (gpu_busy(dcc) or {}).get("job")}

    return _spawn(job, name, spec, dcc, what)


def dispatch(dcc: str | None = None) -> list[dict]:
    """Start queued jobs while the GPU is free. Safe to call from anywhere."""
    started = []
    queued = []
    for n in os.listdir(jobs_dir()):
        s = read_status(n)
        if s.get("state") == "queued" and (dcc is None or s.get("dcc") == dcc):
            queued.append((s.get("created") or 0, n, s))
    queued.sort()
    for _, job, s in queued:
        host = s.get("dcc") or ""
        if host and gpu_busy(host):
            break
        spec = s.get("spec") or {}
        if not spec.get("argv"):
            _write_status(job, state="failed", note="queued job lost its argv")
            continue
        started.append(_spawn(job, s.get("name") or job, spec, host, s.get("what") or ""))
    return started


LOG_CAP = 8 * 1024 * 1024  # a runaway loop cannot fill the disk


def _cap_log(job: str) -> None:
    p = os.path.join(jobs_dir(), job, "log.txt")
    try:
        if os.path.getsize(p) <= LOG_CAP:
            return
        with open(p, "rb") as f:
            f.seek(-LOG_CAP // 2, os.SEEK_END)
            tail = f.read()
        with open(p, "wb") as f:
            f.write(b"[klieg] log truncated to the last 4 MiB\n" + tail)
    except OSError:
        pass


# ------------------------------------------------------------------ history
def _history_file() -> str:
    return os.path.join(data_dir(), "history.json")


def load_history() -> list[dict]:
    try:
        with open(_history_file()) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _record_history(st: dict) -> None:
    secs = float(st.get("ended") or 0) - float(st.get("started") or 0)
    frames = st.get("frames")
    if secs <= 0 or not frames:
        return
    h = load_history()
    h.append({"dcc": st.get("dcc"), "name": st.get("name"), "frames": int(frames),
              "seconds": round(secs, 2)})
    try:
        with open(_history_file(), "w") as f:
            json.dump(h[-200:], f)
    except OSError:
        pass


def predict(dcc: str, frames: int) -> float | None:
    """Median seconds-per-frame for this host, times the frames asked for.

    A prediction from this machine's own history beats any published benchmark:
    the same 288 frames took 15 min on one scene and 63 on another.
    """
    h = [x for x in load_history() if x.get("dcc") == dcc and x.get("frames")]
    if not h or not frames:
        return None
    per = sorted(x["seconds"] / x["frames"] for x in h)
    return round(per[len(per) // 2] * frames, 1)


def poll(job: str) -> dict:
    st = read_status(job)
    if st.get("state") == "queued":
        dispatch(st.get("dcc") or None)
        st = read_status(job)
    proc = _LIVE.get(job)
    if proc is not None:
        proc.poll()          # reap without blocking, so the child is not left a zombie
    if st.get("state") != "running":
        _LIVE.pop(job, None)
        return st
    _cap_log(job)
    exit_file = os.path.join(jobs_dir(), job, "exit")
    alive = True
    try:
        os.kill(int(st.get("pid", 0)), 0)
    except (ProcessLookupError, ValueError, OSError):
        alive = False

    if os.path.exists(exit_file):
        with open(exit_file) as f:
            code = int((f.read() or "1").strip() or 1)
        state = "done" if code == 0 else "failed"
        _write_status(job, state=state, exit=code, ended=time.time())
        if state == "done":
            _record_history(read_status(job))
        if st.get("dcc"):
            release_lock(st["dcc"], job)
        return read_status(job)

    if not alive:
        _write_status(job, state="failed", exit=None,
                      note="process gone without writing an exit code", ended=time.time())
        if st.get("dcc"):
            release_lock(st["dcc"], job)
        return read_status(job)

    return st


def verify(job: str) -> dict:
    """Did the job actually produce what it promised?

    Artefacts must exist AND be newer than the job start. A stale frame from an
    earlier render is the failure mode that looks like success.
    """
    st = poll(job)
    started = float(st.get("started") or 0)
    out = {"job": job, "state": st.get("state"), "artefacts": [], "stale": [], "missing": []}
    for path in st.get("guard", []):
        if not os.path.exists(path):
            out["missing"].append(path)
            continue
        mtime = os.path.getmtime(path)
        (out["stale"] if mtime < started else out["artefacts"]).append(
            {"path": path, "mtime": mtime, "age_s": round(time.time() - mtime, 1)})
    out["ok"] = (st.get("state") == "done" and not out["missing"] and not out["stale"])

    # A guard on one file proves one file. When the job promised N frames, count them:
    # a render that dies at frame 3 of 288 must not verify just because it wrote one frame.
    exp = st.get("expect") or {}
    if exp.get("dir"):
        d, ext = exp["dir"], exp.get("ext", ".png")
        try:
            fresh = [n for n in os.listdir(d)
                     if n.endswith(ext) and os.path.getmtime(os.path.join(d, n)) >= started]
        except OSError:
            fresh = []
        need = int(exp.get("min") or 0)
        out["counted"] = len(fresh)
        out["expected_min"] = need
        if need and len(fresh) < need:
            out["ok"] = False
            out.setdefault("shortfall", need - len(fresh))
    return out


def kill(job: str) -> dict:
    st = read_status(job)
    pid = int(st.get("pid") or 0)
    if pid:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    p = _LIVE.pop(job, None)
    if p is not None:
        try:
            p.wait(timeout=3)
        except Exception:
            pass
    _write_status(job, state="killed", ended=time.time())
    if st.get("dcc"):
        release_lock(st["dcc"], job)
    return read_status(job)


def list_jobs(limit: int = 20) -> list[dict]:
    found = []
    for name in os.listdir(jobs_dir()):
        st = poll(name)
        if st.get("state") == "unknown":
            continue
        found.append(st)
    found.sort(key=lambda s: float(s.get("started") or s.get("created") or 0), reverse=True)
    out = []
    for s in found[:limit]:
        row = {k: s.get(k) for k in ("job", "name", "what", "dcc", "state", "exit",
                                     "started", "ended", "position")}
        if s.get("state") == "queued":
            row["position"] = _queue_position(s["job"])
        out.append(row)
    return out
