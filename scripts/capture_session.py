"""Record a real PTY session of the Klieg CLI, with timestamps.

    <venv>/python scripts/capture_session.py

Writes docs/media/cast.json: [[t_seconds, text], ...] captured from an actual
pseudo-terminal running the actual commands. The demo video replays these bytes at
these times - it is a recording, not a mock-up.
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

SCRIPT = r"""
export PS1='klieg $ '
export TERM=xterm-256color
cd {repo}
printf '\033[1;34mklieg\033[0m  a DCC bridge for Hermes\n'
sleep 0.4
echo "$ klieg probe"
python3 scripts/klieg_cli.py probe
sleep 0.9
printf '\n# the render that finished before the scene was rebuilt\n'
sleep 0.5
STALE=$(python3 - <<'PY'
import sys, os, time, tempfile
sys.path.insert(0, '.')
import klieg_core as c
d = tempfile.mkdtemp(prefix='klieg-cast-stale-')
p = os.path.join(d, '0000.png')
open(p, 'wb').write(b'not a frame')
t = time.time() - 3600
os.utime(p, (t, t))
j = c.launch('stale', ['/bin/sh', '-c', 'true'], guard=[p], what='frame predates the job')
print(j['job'])
PY
)
sleep 1.2
echo "$ klieg jobs verify --job $STALE"
python3 scripts/klieg_cli.py jobs verify --job "$STALE"
sleep 1.6
echo "$ klieg plan --frames 0-287 --out {work}"
python3 scripts/klieg_cli.py plan --blend {blend} --frames 0-287 --out {work}
sleep 1.4
echo "$ klieg render --frames 0-1 --pct 25 --samples 32 --out {work}"
JOB=$(python3 scripts/klieg_cli.py render --blend {blend} --frames 0-1 --pct 25 --samples 32 --out {work} --name demo 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin)["job"])')
echo "  job $JOB"
for i in $(seq 1 40); do
  S=$(python3 scripts/klieg_cli.py jobs status --job "$JOB" 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin).get("state","?"))')
  if [ "$S" != "running" ]; then break; fi
  sleep 1
done
echo "  state $S"
sleep 1.2
echo "$ klieg jobs verify --job $JOB"
python3 scripts/klieg_cli.py jobs verify --job "$JOB"
sleep 1.4
echo "$ klieg publish --frames {work} --out /tmp/klieg-cast/demo.mp4"
python3 scripts/klieg_cli.py publish --frames {work} --out /tmp/klieg-cast/demo.mp4
sleep 1.5
"""


def main() -> int:
    os.makedirs("/tmp/klieg-cast", exist_ok=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    script = SCRIPT.format(repo=REPO, blend=BLEND, work=WORK)

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
