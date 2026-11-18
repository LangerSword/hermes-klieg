"""Built-in gates: numbers over a frame directory, no DCC required.

DESIGN.md's gate library, first four entries. A gate is a measurement, not a
verdict - except where a published guideline exists (flash rate), and then the
guideline is named and the approximation is stated.

    flash      full-field luminance transitions per second (photosensitivity
               screening approximation, NOT a certified Harding test)
    loop       first-vs-last frame difference: does the sequence close?
    stats      per-frame exposure/clipping distribution + temporal stability
    safe_band  fraction of detail (edge energy) inside platform UI margins

All of them read numbered PNGs (NNNN.png) in frame order and need only
numpy + Pillow. Frames are downsampled to <=320px wide for speed; the numbers
are relative, so the ranking survives the downsample. 16-bit grayscale is
scaled explicitly because Pillow's convert("RGB") clips I;16 at 255.
"""

from __future__ import annotations

import os
import re

_NUM_PNG = re.compile(r"^\d+\.png$")
MAX_WIDTH = 320


def _deps():
    import numpy as np
    from PIL import Image
    return np, Image


def _frame_files(frames_dir: str) -> list[str]:
    try:
        names = sorted((n for n in os.listdir(frames_dir) if _NUM_PNG.fullmatch(n)),
                       key=lambda n: int(n[:-4]))
    except OSError:
        return []
    return [os.path.join(frames_dir, n) for n in names]


def _load(path: str):
    np, Image = _deps()
    im = Image.open(path)
    if im.width > MAX_WIDTH:
        im = im.resize((MAX_WIDTH, max(1, round(im.height * MAX_WIDTH / im.width))))
    if im.mode.startswith("I;16") or im.mode == "I":
        g = np.asarray(im).astype(np.float32) / 65535.0
        return np.stack([g, g, g], axis=-1)
    return np.asarray(im.convert("RGB")).astype(np.float32) / 255.0


def _linear_luma(rgb):
    np, _ = _deps()
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return lin[..., 0] * 0.2126 + lin[..., 1] * 0.7152 + lin[..., 2] * 0.0722


def _flash(files: list[str], fps: int, params: dict) -> dict:
    np, _ = _deps()
    delta = float(params.get("luma_delta", 0.10))
    area = float(params.get("area_frac", 0.25))
    means, changed = [], []
    prev = None
    for p in files:
        L = _linear_luma(_load(p))
        means.append(float(L.mean()))
        if prev is not None:
            changed.append(float((np.abs(L - prev) > delta).mean()))
        prev = L
    transitions = [i for i in range(1, len(means))
                   if abs(means[i] - means[i - 1]) > delta and changed[i - 1] > area]
    # densest 1-second window (frame indices stand in for time at fps)
    max_rate = 0
    for t in transitions:
        max_rate = max(max_rate, sum(1 for u in transitions if t <= u < t + fps))
    flashes_per_second = max_rate / 2.0  # a flash is a pair of opposite transitions
    return {
        "frames": len(files), "fps": fps,
        "transitions": len(transitions), "transition_frames": transitions,
        "max_transitions_per_second": max_rate,
        "max_flashes_per_second": flashes_per_second,
        "guideline": "no more than 3 flashes per second (photosensitivity screening)",
        "passes_guideline": flashes_per_second <= 3.0,
        "note": ("approximation: full-field relative luminance on downsampled frames, "
                 "not a certified Harding test; small-area flashes are excluded by area_frac"),
    }


def _loop(files: list[str], fps: int, params: dict) -> dict:
    np, _ = _deps()
    a, b = _load(files[0]), _load(files[-1])
    if a.shape != b.shape:
        return {"error": "first and last frame have different shapes; cannot compare"}
    d = np.abs(a - b).mean(axis=2)
    thresh = float(params.get("pixel_delta", 0.02))
    ys, xs = np.where(d > thresh)
    bbox = None
    if len(ys):
        h, w = d.shape
        bbox = [round(float(xs.min()) / w, 4), round(float(ys.min()) / h, 4),
                round(float(xs.max() + 1) / w, 4), round(float(ys.max() + 1) / h, 4)]
    mean_diff = float(d.mean())
    return {
        "frames": len(files),
        "mean_abs_diff": round(mean_diff, 5),
        "max_abs_diff": round(float(d.max()), 5),
        "changed_fraction": round(float((d > thresh).mean()), 5),
        "changed_bbox": bbox,
        "loop_closed": mean_diff < float(params.get("close_epsilon", 0.005)),
        "note": "0.0 mean_abs_diff is achievable by construction; anything else is a visible seam",
    }


def _stats(files: list[str], fps: int, params: dict) -> dict:
    np, _ = _deps()
    rows = []
    for p in files:
        rgb = _load(p)
        lum = rgb.mean(axis=2)
        mx = rgb.max(axis=2)
        rows.append({"luma_mean": float(lum.mean()),
                     "luma_p95": float(np.percentile(lum, 95)),
                     "clip_hi": float((mx >= 0.985).mean()),
                     "clip_lo": float((mx <= 0.02).mean())})
    means = [r["luma_mean"] for r in rows]
    return {
        "frames": len(files),
        "luma_mean": round(float(np.mean(means)), 5),
        "temporal_std": round(float(np.std(means)), 5),
        "exposure_drift": round(means[-1] - means[0], 5),
        "clip_hi_max": round(max(r["clip_hi"] for r in rows), 5),
        "clip_lo_max": round(max(r["clip_lo"] for r in rows), 5),
        "per_frame": [{k: round(v, 5) for k, v in r.items()} for r in rows],
        "note": "temporal_std near 0 means stable exposure; drift is last minus first",
    }


def _safe_band(files: list[str], fps: int, params: dict) -> dict:
    np, _ = _deps()
    margins = {"top": 0.12, "bottom": 0.18, "left": 0.06, "right": 0.06}
    margins.update(params.get("margins") or {})
    worst = {k: 0.0 for k in margins}
    for p in files:
        grey = _load(p).mean(axis=2)
        h, w = grey.shape
        e = np.zeros_like(grey)
        e[:, :-1] += np.abs(np.diff(grey, axis=1))
        e[:-1, :] += np.abs(np.diff(grey, axis=0))
        total = float(e.sum())
        if total <= 1e-9:
            continue
        bands = {
            "top": e[:max(1, int(h * margins["top"])), :],
            "bottom": e[h - max(1, int(h * margins["bottom"])):, :],
            "left": e[:, :max(1, int(w * margins["left"]))],
            "right": e[:, w - max(1, int(w * margins["right"])):],
        }
        for k, region in bands.items():
            worst[k] = max(worst[k], float(region.sum()) / total)
    return {
        "frames": len(files), "margins": margins,
        "worst_detail_fraction": {k: round(v, 5) for k, v in worst.items()},
        "note": ("edge energy inside each UI margin, worst frame; high fractions mean "
                 "detail the platform's overlays may cover"),
    }


GATES = {"flash": _flash, "loop": _loop, "stats": _stats, "safe_band": _safe_band}


def run(gate: str, frames_dir: str, fps: int = 30, params: dict | None = None) -> dict:
    if gate not in GATES:
        return {"error": f"unknown gate {gate!r}; try one of {sorted(GATES)}"}
    files = _frame_files(frames_dir)
    if not files:
        return {"error": f"no numbered PNG frames (NNNN.png) in {frames_dir}"}
    if gate == "loop" and len(files) < 2:
        return {"error": "loop needs at least two frames"}
    out = GATES[gate](files, fps, params or {})
    return {"gate": gate, **out}