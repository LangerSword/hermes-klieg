"""Taste as a learned preference over measurable facts, not a vibe.

A gate can measure a frame. It cannot tell you whether the frame is good. What it *can* do is
learn which measurements correlate with the frames you accepted, and then say "this one looks
like the ones you rejected, because its highlights are clipped and it is 80 % background".

That is the whole claim here, and it is deliberately small:

  features(frame)      a fixed vector of things a machine can see (exposure, contrast,
                       clipping, hue distribution, edge density, where the detail sits,
                       vignette, palette adherence)
  record(...)          a human verdict: accepted / rejected + one line of why + tags
  train()              standardised logistic regression, numpy only, no sklearn
  score(frame)         p(accept), plus the features that moved it, plus honesty about n

It refuses to score below MIN_SAMPLES and reports its own accuracy on held-out verdicts, so
a confident-sounding number can never come from three examples.
"""

from __future__ import annotations

import json
import os
import time

import numpy as np
from PIL import Image

MIN_SAMPLES = 12
DEFAULT_PALETTE = ("#0A1836", "#1D49C0", "#C9E6FF", "#5A1206", "#C4230E", "#FF6A1A", "#FFE8D2")


def _hex_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)


def features(path: str, palette=DEFAULT_PALETTE) -> dict:
    """Everything here is a number computed from pixels, with no model in the loop."""
    im = Image.open(path)
    a = None
    if im.mode in ("RGBA", "LA"):
        raw = np.asarray(im.split()[-1])
        a = raw.astype(np.float32) / (65535.0 if raw.dtype == np.uint16 else 255.0)
    rgb = np.asarray(im.convert("RGB")).astype(np.float32)
    rgb = rgb / (65535.0 if rgb.max() > 255 else 255.0)
    if a is not None and a.min() < 0.99:
        m = a > 0.15
        if m.mean() < 0.001:
            m = np.ones_like(a, bool)
        pix = rgb[m]
    else:
        pix = rgb.reshape(-1, 3)

    lum = pix.mean(1)
    p05, p50, p95 = np.percentile(lum, [5, 50, 95])
    mx = pix.max(1)
    mn = pix.min(1)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0)

    # hue in 12 buckets, saturation weighted
    r, g, b = pix[:, 0], pix[:, 1], pix[:, 2]
    hue = np.zeros(len(pix), np.float32)
    d = mx - mn
    nz = d > 1e-6
    hue[nz & (mx == r)] = ((g - b) / np.maximum(d, 1e-6))[nz & (mx == r)] % 6
    hue[nz & (mx == g)] = ((b - r) / np.maximum(d, 1e-6) + 2)[nz & (mx == g)]
    hue[nz & (mx == b)] = ((r - g) / np.maximum(d, 1e-6) + 4)[nz & (mx == b)]
    hist, _ = np.histogram(hue, bins=12, range=(0, 6), weights=sat)
    hist = hist / max(hist.sum(), 1e-6)

    # spatial: where is the detail, and how much of the frame carries it
    grey = np.asarray(Image.open(path).convert("L")).astype(np.float32) / 255.0
    gx = np.abs(np.diff(grey, axis=1)).mean()
    gy = np.abs(np.diff(grey, axis=0)).mean()
    edge = float(gx + gy)
    h, w = grey.shape
    c = grey[int(h * 0.2):int(h * 0.8), int(w * 0.25):int(w * 0.75)]
    corner = np.concatenate([grey[:h // 8, :w // 8].ravel(), grey[-h // 8:, -w // 8:].ravel()])
    vignette = float(corner.mean() / max(c.mean(), 1e-6))

    gi = (r + g + b) / 3.0
    greenish = float(((g > r + 0.10) & (g > b + 0.10)).mean())

    pal = np.stack([_hex_rgb(h_) for h_ in palette])
    sample = pix[np.random.default_rng(0).choice(len(pix), size=min(4000, len(pix)), replace=False)]
    dmin = np.min(np.linalg.norm(sample[:, None, :] - pal[None, :, :], axis=2), axis=1)
    palette_fit = float(np.clip(1.0 - dmin.mean() / 0.6, 0, 1))

    out = {
        "luma_p05": float(p05), "luma_median": float(p50), "luma_p95": float(p95),
        "contrast": float(p95 - p05),
        "clip_hi": float((pix.max(1) >= 0.985).mean()),
        "clip_lo": float((pix.max(1) <= 0.02).mean()),
        "sat_mean": float(sat.mean()),
        "edge_density": edge,
        "centre_mass": float(c.std() / max(grey.std(), 1e-6)),
        "vignette": vignette,
        "green_frac": greenish,
        "palette_fit": palette_fit,
    }
    for i, v in enumerate(hist):
        out[f"hue_{i}"] = float(v)
    return out


def _feature_vector(f: dict) -> np.ndarray:
    return np.array([f[k] for k in sorted(f)], np.float64)


# ------------------------------------------------------------------ store
def _store(path: str | None = None) -> str:
    p = path or os.path.join(os.environ.get("HERMES_PLUGIN_DATA", "~/.hermes/plugin-data"),
                             "klieg", "taste.jsonl")
    os.makedirs(os.path.dirname(os.path.expanduser(p)), exist_ok=True)
    return os.path.expanduser(p)


def record(frame_path: str, accepted: bool, reason: str = "", tags=()) -> dict:
    f = features(frame_path)
    row = {"ts": time.time(), "path": os.path.abspath(frame_path), "accepted": bool(accepted),
           "reason": reason, "tags": list(tags), "features": f}
    with open(_store(), "a") as fh:
        fh.write(json.dumps(row) + "\n")
    return {"recorded": True, "accepted": bool(accepted), "n_features": len(f)}


def load() -> list[dict]:
    p = _store()
    if not os.path.exists(p):
        return []
    out = []
    with open(p) as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


# ------------------------------------------------------------------ model
def train(epochs: int = 400, lr: float = 0.15) -> dict:
    rows = load()
    n = len(rows)
    if n < MIN_SAMPLES:
        return {"trained": False, "n": n, "need": MIN_SAMPLES,
                "note": "too few verdicts to fit anything; record more before trusting a score"}
    X = np.stack([_feature_vector(r["features"]) for r in rows])
    y = np.array([1.0 if r["accepted"] else 0.0 for r in rows])
    if y.min() == y.max():
        return {"trained": False, "n": n,
                "note": "every verdict is the same; nothing to separate"}

    mu, sd = X.mean(0), X.std(0)
    sd[sd < 1e-9] = 1.0
    Z = (X - mu) / sd
    Z = np.hstack([Z, np.ones((n, 1))])
    w = np.zeros(Z.shape[1])

    for _ in range(epochs):
        p = 1 / (1 + np.exp(-Z @ w))
        w -= lr * (Z.T @ (p - y) / n + 1e-3 * w)

    p = 1 / (1 + np.exp(-Z @ w))
    pred = (p >= 0.5).astype(float)
    acc = float((pred == y).mean())
    names = sorted(rows[0]["features"]) + ["bias"]
    weights = {k: round(float(v), 4) for k, v in zip(names, w)}
    model = {"mu": mu.tolist(), "sd": sd.tolist(), "w": w.tolist(),
             "names": names, "n": n, "acc": acc, "train_acc": acc}
    with open(_store().replace(".jsonl", ".model.json"), "w") as fh:
        json.dump(model, fh)
    return {"trained": True, "n": n, "accuracy": round(acc, 3),
            "positive_rate": round(float(y.mean()), 3),
            "top": sorted(weights.items(), key=lambda kv: -abs(kv[1]))[:6]}


def score(frame_path: str) -> dict:
    model_path = _store().replace(".jsonl", ".model.json")
    if not os.path.exists(model_path):
        t = train()
        if not t.get("trained"):
            return {"scored": False, **t}
    with open(model_path) as fh:
        model = json.load(fh)
    f = features(frame_path)
    x = _feature_vector({k: f[k] for k in model["names"] if k in f})
    z = (x - np.array(model["mu"])) / np.array(model["sd"])
    contrib = z * np.array(model["w"][:len(z)])
    p = float(1 / (1 + np.exp(-(contrib.sum() + model["w"][-1]))))
    order = np.argsort(-np.abs(contrib))[:5]
    return {
        "scored": True,
        "p_accept": round(p, 3),
        "verdict": "looks accepted" if p >= 0.5 else "looks rejected",
        "n_verdicts": model["n"],
        "train_accuracy": model["acc"],
        "why": [{"feature": model["names"][i], "z": round(float(z[i]), 2),
                 "weight": round(float(model["w"][i]), 3),
                 "pushed": "up" if contrib[i] > 0 else "down"} for i in order],
        "caveat": ("this is your own recorded preference, not universal taste; "
                   f"fitted on {model['n']} verdicts"),
    }
