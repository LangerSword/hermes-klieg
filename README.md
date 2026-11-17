# Klieg

A DCC bridge for Hermes.

Hermes writes a render script in one second. Then the render runs for forty minutes. The
shell times out. The exit code is lost. You do not know if the frames exist.

Klieg moves that work into a job. The job is detached. It writes a log. It writes its own
exit code. Klieg calls the job done only when the files on disk are newer than the job start.

**[Catalog entry](catalog/klieg.yaml)** · if this is useful, a star helps the next person find it.

![how klieg works](docs/media/whiteboard.png)

*Whiteboard: agent, approval gate, adapter, job directory, verify. 1600x900.*

**[50s explainer](docs/media/klieg_demo.mp4)** — motion UI, not a product capture.
Rebuild: `node scripts/record_explainer.cjs` then mux (see `scripts/record_explainer.py`).
Source: [`docs/explainer/index.html`](docs/explainer/index.html).

## Five decisions

**1. A job is done only when its artefact is newer than the job start.**
`klieg_jobs action=verify` compares each expected file with the job start time. It also
counts the frames. A render that stops at frame 3 of 288 fails. A render that emits 288
frames from a scene that did not rebuild fails.

**2. Plan costs nothing.**
`klieg_plan` returns the argv, the expected files, a predicted duration, and the blockers.
It does not start a render. Check a weak model in one call, before it spends an hour.

**3. One GPU, one render.**
`klieg_render` takes a lock for each host. A second render enters the queue and reports its
position. `queue=false` refuses the render.

**4. Approval is per verb.**
Six verbs execute code or use the GPU. Each verb sends an approval request. Read-only verbs
do not. Unattended runs fail closed.

**5. Colour is a record, not a tag.**
`klieg_colour action=write` stores the view transform, the look, the exposure, and the
sha256 of the OCIO config in `colour_manifest.json`. `action=compare` reports each field
that changed. A different view transform gives a different film.

## Tools

| tool | use |
|---|---|
| `klieg_probe` | list the hosts on this machine and their versions |
| `klieg_plan` | resolve a render without running it |
| `klieg_scene` | read the engine, resolution, frame range, view transform, and object count |
| `klieg_run` | run a script in a host; detach it when it is long |
| `klieg_render` | render a frame range as a job that can resume |
| `klieg_track` | run a projection script and confirm the file it wrote |
| `klieg_gate` | run a measurement script that prints `KLIIEG_GATE {json}` |
| `klieg_jobs` | list, queue, status, log, verify, kill |
| `klieg_publish` | encode frames with BT.709 conversion and colour tags |
| `klieg_session` | open a socket to a running Blender, run code, read colour state, stop |
| `klieg_colour` | write, compare, or check a colour manifest |
| `klieg_taste` | record verdicts, train a preference, score a frame |

## Run it

```sh
git clone https://github.com/LangerSword/hermes-klieg ~/.hermes/plugins/klieg
hermes plugins enable klieg
# Start a new session. Then list the hosts:
klieg_probe

# Proof 1: render two frames, verify them, encode them.
python3 scripts/e2e.py

# Proof 2: start a real Blender and drive it over a socket.
python3 scripts/test_bridge.py

# The test suite. No Blender and no GPU are necessary.
python3 -m unittest discover -s tests
```

Blender finds its Python library from the first `python3` on `PATH`. A pyenv or conda entry
breaks that lookup. Run Blender with `PATH=/usr/bin:/bin`.

## Evidence

| check | command | result |
|---|---|---|
| tests | `python3 -W error::ResourceWarning -m unittest discover -s tests` | 38 tests, OK, no warnings |
| live bridge | `python3 scripts/test_bridge.py` | 10 of 10 checks against Blender 5.3.0 |
| end to end | `python3 scripts/e2e.py` | 2 frames rendered, verified, encoded, 20,844 bytes |
| plugin admission | `hermes plugins validate .` | validation passed |
| registration | `hermes plugins doctor .` | 12 tools, 1 hook |

`VERIFICATION.md` gives each check with its output, and each claim that is not verified.

## Limits

- This repository includes the GUI add-on. The tests do not cover it. This machine had no
  interactive Blender. The headless server uses the same protocol, and it passes the bridge test.
- The live bridge supports Blender only. Houdini, Nuke, and After Effects need their own
  protocols.
- The taste model has no real verdicts. It refuses to score below 12 verdicts.
- `klieg_publish` has encoded two frames, not a full film.

## Security

Read `SECURITY.md` before you install.

- Children get a 13-variable environment allow-list.
- Klieg drops any name that matches KEY, TOKEN, SECRET, or PASSWORD. It records the drop.
- `klieg_publish` refuses to write under `/etc`, `/usr`, `~/.ssh`, and `~/.aws`.
- Klieg is not a sandbox. An approved script is arbitrary code.

## Stack

| component | role |
|---|---|
| Python 3.10+ standard library | the plugin, the job engine, the socket client |
| Blender 4.2 or later | the render host; 4.2 has the Khronos view transform |
| ffmpeg | encode, colour tags, probe |
| POSIX unix socket | the live bridge; no TCP port |

## Layout

```
plugin.yaml           manifest: 12 tools
klieg_core.py         jobs, queue, history, locks, verify
klieg_adapters.py     six hosts, one interface
klieg_tools.py        the verbs
klieg_hooks.py        approval policy
klieg_bridge.py       unix socket client
klieg_colour.py       manifest, diff, tag check
klieg_taste.py        features, verdicts, model
blender/              headless server and GUI add-on
scripts/              cli, e2e, bridge test, whiteboard, demo cutter, qa
tests/                38 cases, hermetic
```

MIT. The whiteboard, the demo, and the sample frames in this repository come from the
scripts in `scripts/`.
