# Klieg — design

## Thesis

The hard part of driving a DCC from an agent is not generating the script. Models are good
at that now. The hard part is **surviving the wall-clock**: a render is 20–70 minutes, the
agent's shell is not, and every naive bridge loses the thing you needed — whether the work
actually happened.

So Klieg is not a Blender wrapper. It is three invariants with adapters dangling off them:

1. **A job's truth is its artefact, not its exit code.** `verify()` requires each promised
   file to exist *and* to be newer than the job's start time.
2. **One GPU, one render.** A lock per host, held by pid, released on exit or reaped when
   the holder is gone.
3. **Every host is a shell command.** Adapters produce argv; they never own a process
   lifecycle, a log format, or a retry policy.

## Adapter protocol

An adapter answers three questions and nothing else:

```python
class Adapter:
    name: str                      # "blender"
    binaries: tuple[str, ...]      # shutil.which candidates
    def detect(self) -> dict       # {dcc, found, path, version}
    def run_argv(self, script, blend=None, args=None) -> list[str]
    def render_argv(self, frames, outdir, samples, pct, blend, tag="") -> list[str]
```

Adding Houdini support is `hython script.py`. Adding Nuke is `nuke -t script.py`. The
per-host knowledge lives in exactly one file and is reviewable in a minute — which is the
only way a multi-DCC bridge stays honest instead of becoming six half-working plugins.

**The Blender PATH rule is not optional.** Blender resolves its stdlib from the first
`python3.X` on `PATH`; a pyenv/uv/conda prefix ahead of `/usr/bin` makes it adopt that home,
lose `math`, and fail to register Cycles — which presents as `enum "CYCLES" not found`. Every
launch goes through `SAFE_ENV`.

## Where hooks earn their keep

`pre_tool_call` is the obvious one (approval for the five executing verbs). The interesting
ones are not implemented yet and are the actual product:

| hook / middleware | what it would do |
|---|---|
| `post_tool_call` | hash each produced artefact automatically — the ledger does this on demand via `klieg_ledger seal`; a hook would make it implicit |
| middleware (GPU arbiter) | done as engine queue: per-host locks, FIFO dispatch, predicted duration from history |
| `session_start` | load `shot.yaml` (object, field, palette, frame budget) so every tool call is scoped to one piece of work |
| `pre_tool_call` (scene guard) | refuse a render whose blend is older than its build log — the stale-geometry trap, caught before 20 minutes are spent. The ledger's `check` catches the same drift after the fact; the guard would catch it before |

## Gates as a first-class verb

`klieg_gate` takes two paths: a built-in gate (`gate=flash|loop|stats|safe_band`) measured
directly over a frame directory with numpy/Pillow — no DCC, no model-authored code, no
approval prompt — or a script inside a DCC that must print `KLIIEG_GATE {json}`. It
deliberately does not return pass/fail (except where a published guideline exists, and then
the guideline is named), because the interesting gates are the ones a machine
can measure but not judge:

- loop closure: bbox delta between last and first frame (0.00 px is achievable by construction)
- seam continuity: spread jump at act boundaries, **excluding parts whose box leaves frame**
- flash rate: full-field luminance flips per second
- safe band: readable pixels inside the platform's UI zones (0 px is the only pass)
- compression survival: HUD edge energy retained after a 720p / 2.5 Mb/s re-encode

The last one is why the plugin exists in this shape: a film can look right and measure wrong,
and only a gate that runs the platform's own encode tells you.

## Roadmap

**0.1** — six adapters declared, Blender working, detached jobs, GPU lock,
artefact verification, BT.709 publish.

**0.2 — the live bridge. DONE.** A headless Blender server on a 0600 unix socket,
`klieg_session` start/status/eval/colour/stop/list, busy-vs-dead distinction, dead-session
pruning. The batch path stays the default: a socket into a UI dies with the UI. The GUI
add-on shares the protocol but is untested on an interactive session.

**0.3 — the shot ledger. DONE, as a verb.** `klieg_ledger seal/check/show` hashes scene,
script, every frame (per-file sha256 + hash-list root), colour manifest and encode; publish
seals link back to their source frame root. Implemented as an explicit verb rather than a
`post_tool_call` hook: sealing is a decision the user makes about a finished job, not a
side effect of every tool call.

**0.4 — queue, not lock. DONE.** Per-host pid locks, FIFO queue with per-host position,
dispatch on poll/list/kill, duration prediction from this machine's history. A busy host
does not strand a free host's queue.

**0.5 — gate library. STARTED.** Built-in `flash`, `loop`, `stats`, `safe_band` run over any
numbered PNG sequence with numpy/Pillow, no DCC. Remaining from the original list: seam
continuity at act boundaries and compression-survival (re-encode at platform bitrate,
measure retained edge energy).

**0.2.0 (this repo)** — all of the above plus the limits fixes: queue reachable from the
tool, publish handles mid-sequence and gapped frame sets, structured input errors
everywhere, unique confined render scripts, held-out taste accuracy, per-action approval.
Validates and registers 13 tools + 1 hook.

## Publication

Same path the Pilot plugin took: a standalone repo, a catalog PR against
`NousResearch/hermes-agent`, and a validation transcript in the README. The bar is evidence,
not adjectives — `hermes plugins validate .` and `hermes plugins doctor .` outputs, plus a
smoke test that demonstrates the stale-artefact catch, because that is the claim no other
bridge makes.
