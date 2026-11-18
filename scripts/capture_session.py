"""Record a real PTY session of the Klieg 0.2.0 CLI, with timestamps.

    <venv>/python scripts/capture_session.py

Writes docs/media/cast.json: [[t_seconds, text], ...] captured from an actual
pseudo-terminal running the actual commands. The demo video replays these bytes at
these times - it is a recording, not a mock-up.

The 0.2.0 arc: probe -> render -> verify (artefact truth) -> gate loop -> ledger
seal -> check intact -> re-touch a frame -> check CATCHES the drift. The climax is
the provenance ledger detecting a tampered frame, which is the new differentiator.

Run with the venv interpreter: the built-in gates need numpy/Pillow, which the
bare system python3 lacks. Every python call below uses {py} = sys.executable.
"""

import json
import os
import pty
import select
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import resolve_input
OUT = os.path.join(REPO, "docs/media/cast.json")
BLEND = resolve_input("blend")
WORK = "/tmp/klieg-cast/px"
PY = sys.executable

SCRIPT = r"""
export PS1='klieg $ '
export TERM=xterm-256color
cd {repo}
printf '\033[1;34mklieg\033[0m  a DCC bridge for Hermes\n'
sleep 0.5
echo "$ klieg probe"
{py} scripts/klieg_cli.py probe
sleep 1.2
echo "$ klieg render --frames 1-2 --pct 25 --samples 32 --out {work}"
JOB=$({py} scripts/klieg_cli.py render --blend {blend} --frames 1-2 --pct 25 --samples 32 --out {work} --name demo 2>/dev/null | {py} -c 'import sys,json; print(json.load(sys.stdin)["job"])')
echo "  job $JOB  (detached)"
for i in $(seq 1 40); do
  S=$({py} scripts/klieg_cli.py jobs status --job "$JOB" 2>/dev/null | {py} -c 'import sys,json; print(json.load(sys.stdin).get("state","?"))')
  if [ "$S" != "running" ]; then break; fi
  sleep 1
done
echo "  state $S"
sleep 1.2
echo "$ klieg jobs verify --job $JOB"
{py} scripts/klieg_cli.py jobs verify --job "$JOB"
sleep 1.8
echo "$ klieg gate loop --frames {work}"
{py} scripts/klieg_cli.py gate loop --frames {work}
sleep 1.8
echo "$ klieg ledger seal --job $JOB"
{py} scripts/klieg_cli.py ledger seal --job "$JOB"
sleep 1.8
echo "$ klieg ledger check --job $JOB"
{py} scripts/klieg_cli.py ledger check --job "$JOB"
sleep 1.8
printf '\n# someone re-touches a frame after the render\n'
sleep 0.8
{py} - <<'PY'
from PIL import Image
Image.new("RGB", (480, 270), (200, 40, 40)).save("{work}/0002.png")
PY
echo "$ klieg ledger check --job $JOB"
{py} scripts/klieg_cli.py ledger check --job "$JOB"
sleep 2.4
"""


def main() -> int:
    os.makedirs("/tmp/klieg-cast", exist_ok=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    script = SCRIPT.format(repo=REPO, blend=BLEND, work=WORK, py=PY)

    master, slave = pty.openpty()
    t0 = time.time()
    proc = subprocess.Popen(["/bin/bash", "-lc", script], stdin=slave, stdout=slave,
                            stderr=slave, close_fds=True,
                            env={**os.environ, "PYTHONUNBUFFERED": "1"})
    os.close(slave)

    events = []
    buf = b""
    while True:
        r, _, _ = select.select([master], [], [], 0.25)
        if master in r:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            t = time.time() - t0
            buf += chunk
            text = buf.decode("utf-8", "replace")
            buf = b""
            events.append([round(t, 3), text])
            sys.stdout.write(text)
            sys.stdout.flush()
        elif proc.poll() is not None:
            break
    os.close(master)
    proc.wait(timeout=10)

    json.dump({"events": events, "duration": round(time.time() - t0, 2),
               "blend": BLEND, "work": WORK},
              open(OUT, "w"))
    print(f"\n\nwrote {OUT}: {len(events)} chunks, {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())