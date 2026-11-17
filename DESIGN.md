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
| `post_tool_call` | hash each produced artefact and append to a per-shot ledger — a provable record that this frame came from this scene at this commit |
| middleware (GPU arbiter) | queue renders across hosts instead of refusing them: first come, first served, with a predicted duration from the last run |
| `session_start` | load `shot.yaml` (object, field, palette, frame budget) so every tool call is scoped to one piece of work |
| `pre_tool_call` (scene guard) | refuse a render whose blend is older than its build log — the stale-geometry trap, caught before 20 minutes are spent |

## Gates as a first-class verb

`klieg_gate` runs a script that must print `KLIIEG_GATE {json}` and returns the numbers. It
deliberately does not return pass/fail, because the interesting gates are the ones a machine
can measure but not judge:

- loop closure: bbox delta between last and first frame (0.00 px is achievable by construction)
- seam continuity: spread jump at act boundaries, **excluding parts whose box leaves frame**
- flash rate: full-field luminance flips per second
- safe band: readable pixels inside the platform's UI zones (0 px is the only pass)
- compression survival: HUD edge energy retained after a 720p / 2.5 Mb/s re-encode

The last one is why the plugin exists in this shape: a film can look right and measure wrong,
and only a gate that runs the platform's own encode tells you.

## Roadmap

**0.1 (this repo)** — six adapters declared, Blender working, detached jobs, GPU lock,
artefact verification, BT.709 publish. Validates and registers 8 tools + 1 hook.

**0.2 — the live bridge.** A Blender addon that listens on a unix socket, plus
`session()` in the adapter. The rule: the batch path stays the default, because a socket
into a UI dies with the UI. Reconnect, and a hard timeout, or it is worse than batch.

**0.3 — the shot ledger.** `post_tool_call` hashes artefacts; `klieg_jobs export` writes a
manifest of what was produced, from which scene hash, with which gate numbers.

**0.4 — queue, not lock.** The GPU arbiter predicts duration per host from history and
serialises work instead of refusing it.

**0.5 — gate library.** Ship the measurements above as reusable scripts, so a new project
gets loop/seam/flash/safe-band checks without writing them again.

## Publication

Same path the Pilot plugin took: a standalone repo, a catalog PR against
`NousResearch/hermes-agent`, and a validation transcript in the README. The bar is evidence,
not adjectives — `hermes plugins validate .` and `hermes plugins doctor .` outputs, plus a
smoke test that demonstrates the stale-artefact catch, because that is the claim no other
bridge makes.
