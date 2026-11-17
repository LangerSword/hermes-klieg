"""Measure ASD-STE100 compliance of the README's procedural and specification text.

    python3 scripts/ste_check.py [README.md]

Scope: the tagline, the pitch and the closing line stay in the author's voice and are not
scored. Everything else (decisions, tools, run it, evidence, limits, security, stack,
layout) is checked. A sentence passes when it is short, in the active voice, free of
semicolons, em dashes, contractions, and marketing words.

Prints each failure with its reason, then the share that passed.
"""

from __future__ import annotations

import re
import sys

BANNED = {
    "seamless", "effortless", "powerful", "best", "fastest", "blazing", "robust",
    "cutting-edge", "world-class", "revolutionary", "simply", "just", "obviously",
    "easily", "leverage", "utilize", "enable", "unlock", "supercharge",
}
PASSIVE = re.compile(r"\b(is|are|was|were|be|been|being)\b\s+(\w+ed|\w+en)\b", re.I)
NATURAL_HEADINGS = ("# Klieg",)          # the pitch block, not scored
CLOSING_PREFIX = "MIT."


def sections(text: str) -> list[tuple[str, bool, list[str]]]:
    """(heading, scored?, lines). The block before '## Five decisions' is the pitch."""
    out = []
    heading = "# Klieg"
    scored = False
    lines: list[str] = []
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
            lines.append(line)
            continue
        if not in_code and line.startswith("## "):
            out.append((heading, scored, lines))
            heading, lines = line[3:].strip(), []
            scored = True
            continue
        lines.append(line)
    out.append((heading, scored, lines))
    return out


def sentences(lines: list[str]) -> list[str]:
    """Prose only: no code fences, no table rows, no headings, no italic captions."""
    buf, in_code = [], False
    for ln in lines:
        if ln.startswith("```"):
            in_code = not in_code
            continue
        if in_code or ln.startswith("|") or ln.startswith("#") or ln.startswith("*"):
            continue
        if not ln.strip():
            continue
        stripped = ln.strip()
        if stripped.startswith("- "):
            buf.append(". " + stripped[2:])      # each bullet is its own sentence
            continue
        buf.append(re.sub(r"`[^`]*`", "CODE", stripped))
    text = " ".join(buf)
    text = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text)
    return [p.strip() for p in parts if len(p.split()) >= 3]


def check(s: str, procedural: bool) -> list[str]:
    bad = []
    words = len(s.split())
    limit = 20 if procedural else 25
    if words > limit:
        bad.append(f"{words} words (limit {limit})")
    if PASSIVE.search(s):
        bad.append("passive voice")
    if ";" in s:
        bad.append("semicolon")
    if "—" in s or "–" in s:
        bad.append("dash as connector")
    if re.search(r"\b\w+'(s|t|re|ve|ll|d)\b", s):
        bad.append("contraction")
    low = {w.lower().strip(".,():") for w in s.split()}
    hit = low & BANNED
    if hit:
        bad.append("marketing word: " + ", ".join(sorted(hit)))
    return bad


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "README.md"
    text = open(path).read()
    total = passed = 0
    failures = []
    for heading, scored, lines in sections(text):
        if not scored:
            continue
        for s in sentences(lines):
            if s.startswith(CLOSING_PREFIX):
                continue
            total += 1
            bad = check(s, procedural=True)
            if bad:
                failures.append((heading, s, bad))
            else:
                passed += 1
    for heading, s, bad in failures:
        print(f"FAIL [{heading}] {s[:96]}")
        print(f"     -> {', '.join(bad)}")
    pct = 100 * passed / max(total, 1)
    print(f"\n{passed}/{total} specification sentences comply: {pct:.1f}%")
    return 0 if pct >= 80 else 1


if __name__ == "__main__":
    raise SystemExit(main())
