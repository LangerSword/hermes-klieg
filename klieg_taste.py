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

MIN_SAMPLES = 12
DEFAULT_PALETTE = ("#0A1836", "#1D49C0", "#C9E6FF", "#5A1206", "#C4230E", "#FF6A1A", "#FFE8D2")


def _deps():
    """Import image deps only when a verb needs them.

    Registration must not fail because numpy or Pillow is missing. The tools that
    touch pixels report the missing dep as data; probe/run/render never need it.
    """
    import numpy as np
    from PIL import Image
    return np, Image


def _hex_rgb(h):
    np, _ = _deps()
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)


def features(path: str, palette=DEFAULT_PALETTE) -> dict:
    """Everything here is a number computed from pixels, with no model in the loop."""
    np, Image = _deps()
    im = Image.open(path)
    a = None
    if im.mode in ("RGBA", "LA"):
        raw = np.asarray(im.split()[-1])
        a = raw.astype(np.float32) / (65535.0 if raw.dtype == np.uint16 else 255.0)
    if im.mode.startswith("I;16") or im.mode == "I":
        # Pillow's convert("RGB")/convert("L") CLIP 16-bit samples at 255
        # instead of scaling: 1000/65535 would read as full white. Scale the
        # raw array explicitly.
        g = np.asarray(im).astype(np.float32) / 65535.0
        rgb = np.stack([g, g, g], axis=-1)
    else:
        rgb_raw = np.asarray(im.convert("RGB"))
        # Normalize by dtype, not content: a dark 16-bit frame whose samples all
        # happen to be <= 255 is still 16-bit; the old max-value heuristic divided
        # it by 255 and reported a frame 256x too bright.
        rgb = rgb_raw.astype(np.float32) / (65535.0 if rgb_raw.dtype == np.uint16 else 255.0)
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

    # spatial: where is the detail, and how much of the frame carries it.
    # Same luma definition as the pixel stats (mean of channels), so 16-bit
    # frames do not get a second, clipping conversion.
    grey = rgb.mean(axis=2)
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


def _feature_vector(f: dict):
    np, _ = _deps()
    return np.array([f[k] for k in sorted(f)], np.float64)


# ------------------------------------------------------------------ store
def _store(path: str | None = None) -> str:
    if path is None:
        try:
            from . import klieg_core as core
        except ImportError:
            import klieg_core as core
        p = os.path.join(core.data_dir(), "taste.jsonl")
    else:
        p = path
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
def _fit(Z, y, epochs: int, lr: float):
    np, _ = _deps()
    w = np.zeros(Z.shape[1])
    n = len(y)
    for _ in range(epochs):
        p = 1 / (1 + np.exp(-Z @ w))
        w -= lr * (Z.T @ (p - y) / n + 1e-3 * w)
    return w


def train(epochs: int = 400, lr: float = 0.15) -> dict:
    """Fit on all verdicts, but report accuracy on held-out verdicts.

    Stratified k-fold (k up to 5, capped by the minority class): each fold is
    scored by a model that never saw it, with standardisation computed on the
    training fold only. The old code reported training accuracy while the
    docstring promised held-out - a confident number from an overfit model is
    exactly the failure this plugin exists to prevent.
    """
    np, _ = _deps()
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
    Z = np.hstack([(X - mu) / sd, np.ones((n, 1))])
    w = _fit(Z, y, epochs, lr)

    p = 1 / (1 + np.exp(-Z @ w))
    train_acc = float(((p >= 0.5).astype(float) == y).mean())

    # Held-out estimate: stratified folds, deterministic order.
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    k = min(5, len(pos), len(neg))
    cv_acc = None
    if k >= 2:
        rng = np.random.default_rng(7)
        pos, neg = pos.copy(), neg.copy()
        rng.shuffle(pos)
        rng.shuffle(neg)
        folds = [np.concatenate([pos[i::k], neg[i::k]]) for i in range(k)]
        correct = total = 0
        for i in range(k):
            va = folds[i]
            tr = np.concatenate([folds[j] for j in range(k) if j != i])
            mu_t, sd_t = X[tr].mean(0), X[tr].std(0)
            sd_t[sd_t < 1e-9] = 1.0
            Ztr = np.hstack([(X[tr] - mu_t) / sd_t, np.ones((len(tr), 1))])
            Zva = np.hstack([(X[va] - mu_t) / sd_t, np.ones((len(va), 1))])
            wv = _fit(Ztr, y[tr], epochs, lr)
            pv = 1 / (1 + np.exp(-Zva @ wv))
            correct += int(((pv >= 0.5) == y[va]).sum())
            total += len(va)
        cv_acc = correct / total

    acc = cv_acc if cv_acc is not None else train_acc
    names = sorted(rows[0]["features"]) + ["bias"]
    weights = {key: round(float(v), 4) for key, v in zip(names, w)}
    model = {"mu": mu.tolist(), "sd": sd.tolist(), "w": w.tolist(),
             "names": names, "n": n, "acc": acc, "train_acc": train_acc,
             "cv_folds": k if cv_acc is not None else 0}
    with open(_store().replace(".jsonl", ".model.json"), "w") as fh:
        json.dump(model, fh)
    return {"trained": True, "n": n, "accuracy": round(acc, 3),
            "holdout_accuracy": round(cv_acc, 3) if cv_acc is not None else None,
            "train_accuracy": round(train_acc, 3),
            "holdout_note": (f"{k}-fold stratified held-out" if cv_acc is not None else
                             "fewer than 2 verdicts in a class: training accuracy only, treat as unverified"),
            "positive_rate": round(float(y.mean()), 3),
            "top": sorted(weights.items(), key=lambda kv: -abs(kv[1]))[:6]}


def score(frame_path: str) -> dict:
    np, _ = _deps()
    model_path = _store().replace(".jsonl", ".model.json")
    if not os.path.exists(model_path):
        t = train()
        if not t.get("trained"):
            return {"scored": False, **t}
    with open(model_path) as fh:
        model = json.load(fh)
    f = features(frame_path)
    # A model trained on a different feature set (palette or version change)
    # must not silently score with dropped columns: retrain once, then refuse.
    expected = [k for k in model["names"] if k != "bias"]
    if set(expected) != set(f):
        t = train()
        if not t.get("trained"):
            return {"scored": False,
                    "error": "model feature set no longer matches the extractor and retrain failed",
                    **t}
        with open(model_path) as fh:
            model = json.load(fh)
        expected = [k for k in model["names"] if k != "bias"]
        if set(expected) != set(f):
            return {"scored": False,
                    "error": "model feature set no longer matches the extractor; record fresh verdicts"}
    x = _feature_vector({k: f[k] for k in expected})
    z = (x - np.array(model["mu"])) / np.array(model["sd"])
    contrib = z * np.array(model["w"][:len(z)])
    p = float(1 / (1 + np.exp(-(contrib.sum() + model["w"][-1]))))
    order = np.argsort(-np.abs(contrib))[:5]
    return {
        "scored": True,
        "p_accept": round(p, 3),
        "verdict": "looks accepted" if p >= 0.5 else "looks rejected",
        "n_verdicts": model["n"],
        "accuracy": model["acc"],
        "train_accuracy": model.get("train_acc", model["acc"]),
        "holdout": bool(model.get("cv_folds", 0)),
        "why": [{"feature": model["names"][i], "z": round(float(z[i]), 2),
                 "weight": round(float(model["w"][i]), 3),
                 "pushed": "up" if contrib[i] > 0 else "down"} for i in order],
        "caveat": ("this is your own recorded preference, not universal taste; "
                   f"fitted on {model['n']} verdicts"),
    }
