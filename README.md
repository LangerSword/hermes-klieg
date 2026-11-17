# Klieg — a DCC bridge for Hermes

**Give the agent hands on the tools that make pictures.**

Hermes can write a render script in one breath and then lose the next hour to it: a
70-minute Cycles pass wedges the interactive terminal, the shell times out, and the exit
code that told you whether the frames were written is gone. Klieg exists because that is
not a Blender problem, it is a *bridge* problem — and it is the same problem in Houdini,
Nuke, C4D, After Effects and Resolve.

One adapter interface, eight verbs, and a job engine that assumes the shell will die.

## The eight verbs

| tool | what it actually settles |
|---|---|
| `klieg_probe` | what is installed, at what version, and where |
| `klieg_plan` | **resolve a render without running it**: argv, expected files, predicted duration, every blocker |
| `klieg_scene` | engine, resolution, frame range, view transform, objects, vertex totals |
| `klieg_run` | run a script inside the host — blocking for a probe, detached for anything long |
| `klieg_render` | a frame range as a resumable job; **queues** behind the GPU holder instead of refusing |
| `klieg_track` | run a projection/tracking script and confirm the JSON it owed you |
| `klieg_gate` | run a measurement script that must print `KLIIEG_GATE {json}` |
| `klieg_jobs` | list / queue / status / log / **verify** / kill |
| `klieg_publish` | encode with explicit BT.709 and the colour tags in the bitstream |

## Four design decisions that matter more than the code

**1. A job is not done when the process exits — it is done when the artefact is newer than
the job started.** `klieg_jobs action=verify` compares each promised file's mtime against
the launch time. This is the exact failure that ate four hours on a real film: a render
job launched against a blend that had failed to rebuild, emitted a full 288-frame count of
the previous geometry, and reported success. A count is not evidence. An mtime is.

**2. Plan is free; a wrong render is an hour.** `klieg_plan` resolves the argv, the exact
files the pass must produce, a duration predicted from this machine's own history, and every
reason it would fail — without touching the GPU. A weak model can be checked against a plan
in milliseconds. The alternative is discovering the mistake at minute 40.

**3. One GPU, one render is enforced, not requested — and a second request queues rather
than fails.** `klieg_render` takes a lock keyed by the host. With `queue=true` (the default)
the second job is created in the `queued` state and starts the moment the holder exits, with
its position reported; `queue=false` refuses outright. Either way, two Cycles processes never
land on one GPU, because that is how you get a machine that looks hung.

**4. Approval is per verb, not per plugin.** Five tools execute model-authored code or
spend GPU time and go through Hermes's human gate (`klieg:*` rule keys). Probing and scene
inspection stay silent. Unattended runs fail closed.

## Adapters

| host | 0.1 status | mechanism |
|---|---|---|
| Blender | **working** | `blender -b --factory-startup <blend> -P <script> -- <args>` |
| Houdini | declared | `hython script.py` |
| Nuke | declared | `nuke -t script.py` |
| Cinema 4D | declared | version probe only |
| After Effects | declared, not driven | ExtendScript/UXP — reported present-but-unsupported, never silently missing |
| Resolve | declared, not driven | headless scripting needs a running Fusion session |

**Every Blender launch goes through a sanitised `PATH`.** Blender resolves its stdlib from
the first `python3.X` on PATH; a pyenv/uv/conda prefix ahead of `/usr/bin` makes it adopt
that home and lose `math`, so Cycles never registers and the engine enum reports only
EEVEE. It reads exactly like a broken install. It is not.

## Where Klieg sits next to the official `blender` plugin

The catalog already has `blender` — a wrapper around Blender Lab's MCP server that drives a
**live, open Blender** over loopback:9876. That plugin is for poking a scene in front of you.
Its own docs are explicit about what it does not do: *"liveness detection (whether Blender and
its bridge are running) is not verified or implemented"*, *"MCP tool listing alone does not
establish scene readiness"*, and nothing at all about a render that takes an hour.

Klieg is the other half:

| | official `blender` (MCP) | Klieg |
|---|---|---|
| target | a live UI session | a batch process |
| readiness | not implemented (their words) | `klieg_probe` + `klieg_scene` return real scene data |
| long jobs | not addressed | detached, logged, resumable, **artefact-verified** |
| failure mode | bridge dies with the app | exit code survives the shell; stale artefacts are caught |
| scope | Blender | six hosts behind one adapter interface |
| delivery | none | BT.709 encode with colour tags in the bitstream |

They compose: use the MCP plugin to art-direct a shot interactively, then hand the same scene
to Klieg for the pass that must not lie about finishing. Klieg does not require or replace it.

## Evidence

| check | command | result |
|---|---|---|
| unit tests | `python3 -W error::ResourceWarning -m unittest discover -s tests` | 24 tests, OK, no warnings |
| end-to-end | `python3 scripts/e2e.py` | 2 frames rendered → verified → encoded, [20,844 bytes](docs/media/e2e_ig.mp4) |
| admission | `hermes plugins validate .` | validation passed |
| runtime | `hermes plugins doctor .` | 9 tools, 1 hook registered |

Full detail, including everything **not** verified, is in [VERIFICATION.md](VERIFICATION.md).

## Install

```sh
git clone https://github.com/LangerSword/hermes-klieg ~/.hermes/plugins/klieg
hermes plugins enable klieg
# next session:
klieg_probe
```

## Limits, stated plainly

- **No live UI bridge yet.** 0.1 drives batch/headless only. A socket into an open Blender
  or AE session is the obvious 0.2, and it is per-host work: an addon inside the app, a
  protocol, reconnection, and a rule for what happens when the app crashes mid-job.
- **No colour management beyond tags.** Klieg writes BT.709 and tags the stream; it does not
  run an OCIO config of its own.
- **Gates do not know taste.** They return numbers. Whether the frame is good is the human's
  call, and `klieg_gate` says so by returning measurements rather than a pass.
