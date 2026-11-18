"""The shot ledger: a provable record of what a job produced, from what input.

Klieg's verify() answers "did the job write fresh files?". The ledger answers the
next question: "are these STILL the files that job wrote, from that scene, under
that colour management?" It hashes the inputs and outputs at seal time and
re-hashes them on check:

    scene.blend (sha256) ──> render job ──> frames (per-file sha256 + root)
                                              │
                              colour_manifest.json (sha256)
                                              │
                              publish job ──> encode.mp4 (sha256)
                                              └── source frame root (link)

The root is a hash-list commitment: sha256 over the sorted "name:hash" lines.
It is not a signature - anyone who can edit the files can edit the ledger - but
it makes silent drift detectable: a re-rendered frame, a touched-up encode, a
scene edited after the render, a swapped OCIO manifest. For a film delivered to
a platform, "these exact frames came from this exact scene" is a claim you can
now check instead of assert.

Sealing writes only ledger.json inside the job's own directory. No user path is
written, no code is executed, no GPU is touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

try:  # loaded as a Hermes plugin package
    from . import klieg_core as core
except ImportError:  # loaded standalone (tests, scripts)
    import klieg_core as core

LEDGER = "ledger.json"


def _sha256(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _file_record(path: str) -> dict:
    return {"path": path, "sha256": _sha256(path),
            "bytes": os.path.getsize(path) if os.path.exists(path) else None}


def _frames_root(files: list[dict]) -> str:
    """Hash-list commitment over sorted name:hash lines."""
    lines = sorted(f"{os.path.basename(f['path'])}:{f['sha256']}" for f in files)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _frame_files(directory: str, ext: str) -> list[dict]:
    try:
        names = sorted(n for n in os.listdir(directory) if n.endswith(ext))
    except OSError:
        return []
    return [_file_record(os.path.join(directory, n)) for n in names]


def _collect(st: dict) -> dict:
    """Everything the ledger commits to, recomputable from disk."""
    meta = st.get("meta") or {}
    out: dict = {"job": st.get("job"), "state": st.get("state"), "exit": st.get("exit"),
                 "argv": st.get("argv") or []}

    scene = meta.get("blend")
    if scene:
        out["scene"] = _file_record(scene)
    script = meta.get("script")
    if script:
        out["script"] = _file_record(script)

    guards = [_file_record(p) for p in st.get("guard") or []]
    out["artefacts"] = guards

    exp = st.get("expect") or {}
    frames_dir = exp.get("dir") or meta.get("frames_dir")
    if frames_dir:
        ext = exp.get("ext", ".png")
        files = _frame_files(frames_dir, ext)
        out["frames"] = {"dir": frames_dir, "ext": ext, "count": len(files),
                         "root": _frames_root(files), "files": files}
        manifest = os.path.join(frames_dir, "colour_manifest.json")
        if os.path.exists(manifest):
            out["colour_manifest"] = _file_record(manifest)

    # A publish job links back to the frames it encoded: the chain stays
    # checkable even after the frame directory moves on to the next shot.
    if meta.get("frames_dir") and not exp.get("dir"):
        src = _frame_files(meta["frames_dir"], ".png")
        out["source_frames"] = {"dir": meta["frames_dir"], "count": len(src),
                                "root": _frames_root(src)}
    return out


def _root(payload: dict) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def seal(job: str) -> dict:
    if not core.valid_job_id(job):
        return {"ok": False, "error": f"invalid job id: {job!r}"}
    st = core.poll(job)
    if st.get("state") != "done":
        return {"ok": False, "error": f"job is {st.get('state')}, not done; "
                                      "seal only a verified, finished job",
                "hint": "run klieg_jobs action=verify first"}
    payload = _collect(st)
    payload["sealed_at"] = time.time()
    payload["ledger_root"] = _root(payload)
    p = os.path.join(core._job_dir(job), LEDGER)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
    os.replace(tmp, p)
    return {"ok": True, "job": job, "ledger": p,
            "ledger_root": payload["ledger_root"],
            "frames": (payload.get("frames") or {}).get("count"),
            "scene": (payload.get("scene") or {}).get("sha256")}


def show(job: str) -> dict:
    if not core.valid_job_id(job):
        return {"ok": False, "error": f"invalid job id: {job!r}"}
    p = os.path.join(core._job_dir(job), LEDGER)
    if not os.path.exists(p):
        return {"ok": False, "error": f"job {job} has no ledger; seal it first"}
    with open(p) as f:
        return {"ok": True, **json.load(f)}


def check(job: str) -> dict:
    if not core.valid_job_id(job):
        return {"ok": False, "error": f"invalid job id: {job!r}"}
    p = os.path.join(core._job_dir(job), LEDGER)
    if not os.path.exists(p):
        return {"ok": False, "error": f"job {job} has no ledger; seal it first"}
    with open(p) as f:
        sealed = json.load(f)
    now = _collect(core.read_status(job))

    changed, missing = [], []

    def cmp_record(key: str, was: dict | None, now_rec: dict | None):
        if not was:
            return
        if now_rec is None or now_rec.get("sha256") is None:
            missing.append({"what": key, "path": was.get("path")})
        elif now_rec.get("sha256") != was.get("sha256"):
            changed.append({"what": key, "path": was.get("path"),
                            "sealed": was.get("sha256"), "now": now_rec.get("sha256")})

    cmp_record("scene", sealed.get("scene"), now.get("scene"))
    cmp_record("script", sealed.get("script"), now.get("script"))
    cmp_record("colour_manifest", sealed.get("colour_manifest"), now.get("colour_manifest"))
    for was in sealed.get("artefacts") or []:
        now_rec = next((a for a in now.get("artefacts") or [] if a["path"] == was["path"]), None)
        cmp_record("artefact", was, now_rec)

    added = []
    sf, nf = sealed.get("frames"), now.get("frames")
    if sf:
        sealed_paths = {f["path"] for f in sf.get("files") or []}
        now_files = {f["path"]: f for f in (nf or {}).get("files") or []}
        for was in sf.get("files") or []:
            cur = now_files.get(was["path"])
            if cur is None or cur.get("sha256") is None:
                missing.append({"what": "frame", "path": was["path"]})
            elif cur["sha256"] != was["sha256"]:
                changed.append({"what": "frame", "path": was["path"],
                                "sealed": was["sha256"], "now": cur["sha256"]})
        added = [pth for pth in now_files if pth not in sealed_paths]

    source_changed = False
    ss = sealed.get("source_frames")
    if ss:
        ns = now.get("source_frames") or {}
        source_changed = ns.get("root") != ss.get("root")

    # A guarded first/last frame is also in the frames list; report each path
    # once, not once per category.
    def _dedupe(rows: list[dict]) -> list[dict]:
        seen, out = set(), []
        for r in rows:
            if r["path"] not in seen:
                seen.add(r["path"])
                out.append(r)
        return out

    changed, missing = _dedupe(changed), _dedupe(missing)
    intact = not changed and not missing and not added and not source_changed
    return {"ok": True, "job": job, "intact": intact,
            "ledger_root": sealed.get("ledger_root"),
            "changed": changed, "missing": missing, "added_frames": added,
            "source_frames_changed": source_changed,
            "note": ("everything still matches the seal" if intact else
                     "the artefacts or inputs drifted after sealing")}