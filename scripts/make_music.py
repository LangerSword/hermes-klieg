"""Klieg demo score: dark ambient bed, synthesized here, no samples, no voice.

Same recipe family as hermes-portal/make_music.py — pure Python, fixed seed.
"""

from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path

SR = 48000
DUR = 55.0
N = int(SR * DUR)
random.seed(42)

# cooler palette (render bay, not voice band)
CHORDS = [
    [82.41, 98.00, 123.47, 164.81],   # E minor-ish low
    [87.31, 110.00, 130.81, 174.61],  # F
    [92.50, 110.00, 146.83, 185.00],  # F#
    [98.00, 123.47, 146.83, 196.00],  # G
]
SEG = DUR / len(CHORDS)
ATTACK, RELEASE = 2.0, 2.4

left = [0.0] * N
right = [0.0] * N


def env(t_in_seg: float) -> float:
    a = min(1.0, t_in_seg / ATTACK)
    r = min(1.0, (SEG - t_in_seg) / RELEASE)
    return max(0.0, min(a, r)) ** 1.6


for i in range(N):
    t = i / SR
    seg = min(len(CHORDS) - 1, int(t / SEG))
    local = t - seg * SEG
    e = env(local)
    if e <= 0:
        continue
    chord = CHORDS[seg]
    root = chord[0] / 2
    for n, f in enumerate(chord):
        vib = 1.0 + 0.0015 * math.sin(2 * math.pi * (0.06 + n * 0.014) * t)
        v = (
            math.sin(2 * math.pi * f * vib * t)
            + 0.65 * math.sin(2 * math.pi * f * 1.002 * t + n)
        ) * 0.026
        pan = 0.30 + 0.13 * n
        left[i] += v * (1 - pan) * e
        right[i] += v * pan * e
    sub = math.sin(2 * math.pi * root * t) * 0.065 * e
    left[i] += sub
    right[i] += sub
    if i % 2 == 0:
        noise = (random.random() * 2 - 1) * 0.010 * e
        left[i] += noise
        right[i] += noise * 0.75
    pulse_t = t % 7.0
    if pulse_t < 2.0 and e > 0.2:
        decay = math.exp(-pulse_t * 2.8)
        bell = math.sin(2 * math.pi * root * 2.5 * t) * 0.04 * decay * e
        left[i] += bell * 0.65
        right[i] += bell

dL, dR = int(0.17 * SR), int(0.21 * SR)
for i in range(N - 1, max(dL, dR), -1):
    left[i] += 0.18 * right[i - dL]
    right[i] += 0.18 * left[i - dR]

peak = max(1e-9, max(max(abs(v) for v in left), max(abs(v) for v in right)))
gain = 0.55 / peak  # stay under VO presence if mixed later; quiet under captions
fade_in, fade_out = int(1.5 * SR), int(3.5 * SR)
for i in range(N):
    g = gain
    if i < fade_in:
        g *= i / fade_in
    if i > N - fade_out:
        g *= (N - i) / fade_out
    left[i] *= g
    right[i] *= g

out = Path(__file__).resolve().parents[1] / "docs/media/music.wav"
out.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(out), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    buf = bytearray()
    for L, R in zip(left, right):
        buf += struct.pack(
            "<hh",
            max(-32767, min(32767, int(L * 32767))),
            max(-32767, min(32767, int(R * 32767))),
        )
    w.writeframes(buf)
print("wrote", out, DUR, "s")
