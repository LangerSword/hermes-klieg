# Security

Klieg runs code and writes files on your machine. This document states exactly what it can
do, what it refuses to do, and where the remaining risk lives. It is written to be read
before install, not after.

## What Klieg can do

| capability | how | boundary |
|---|---|---|
| execute Python inside a DCC | `klieg_run`, `klieg_track`, `klieg_gate script=…` write/pass a script and launch the host | approval-gated per call |
| spawn long-running processes | `klieg_render`, `klieg_publish` via `subprocess.Popen(start_new_session=True)` | detached, logged, killable by job id |
| write rendered frames and encodes | wherever `outdir` / `out` point | refused under system and credential paths |
| write a colour manifest | `klieg_colour action=write` | approval-gated; same write refusals as publish |
| hash files into a job ledger | `klieg_ledger action=seal` | approval-gated; writes only `ledger.json` inside the job's own directory |
| measure frames | built-in `klieg_gate gate=…`, `klieg_taste`, `klieg_ledger check/show` | read-only; no code execution, no writes outside the plugin data dir |
| read scene files | the DCC opens them | not parsed by Klieg |

It has **no** network access, **no** credential store, and **no** telemetry.

## Approvals

Approval is per **action**, not per tool. These prompt with a `klieg:<tool>` rule key:

- `klieg_run`, `klieg_track`, `klieg_render`, `klieg_publish` (execute code / spend GPU /
  overwrite deliverables)
- `klieg_gate script=…` (executes model-authored Python in a host)
- `klieg_session start/eval/stop` (eval shows the code in the prompt)
- `klieg_colour write`, `klieg_ledger seal`, `klieg_jobs kill/queue`

These pass without a prompt because they cannot change anything outside the plugin's own
data directory: `klieg_probe`, `klieg_scene`, `klieg_plan`, `klieg_taste` (verdicts are
confined to `taste.jsonl`), built-in `klieg_gate gate=…` (reads frames, computes numbers),
`klieg_session status/list/colour`, `klieg_colour probe/compare/tags`, `klieg_ledger
check/show`, and the read-only job actions. `klieg_gate` rejects `gate` and `script`
together, so the free path cannot be used to smuggle a script past the gate. Unattended
runs (cron) fail closed. The policy is tested (`tests/test_hardening.py`,
`tests/test_gates.py`, `tests/test_ledger.py`).

## The child environment is an allow-list, not a copy

A render does not need `OPENAI_API_KEY`, a cloud token, or a database password. Passing
`os.environ` wholesale is how a secret ends up in a logfile a user then pastes into a bug
report. Children receive only:

```
PATH HOME USER LOGNAME LANG LC_ALL LC_CTYPE TERM TMPDIR TZ
XDG_RUNTIME_DIR DISPLAY WAYLAND_DISPLAY
```

plus any explicit per-job `env`. Any name matching `KEY|TOKEN|SECRET|PASSWORD|PASSWD|
CREDENTIAL|SESSION` is **dropped** even if a caller passes it, and the dropped names are
recorded in the job's `status.json` as `env_dropped` so the omission is visible rather than
silent. `test_agent_secrets_do_not_reach_children` asserts this.

## Subprocess construction

- Jobs run as `sh -c "<argv>; echo $? > exit"` where `<argv>` is `shlex.join(argv)`. No
  user string is spliced into a shell line; each element is quoted individually.
- The `sh -c` wrapper exists for one reason: so the **child writes its own exit code**. A
  wrapper that dies before writing is then distinguishable from a job that succeeded, which
  is the entire premise of `verify()`.
- Every launch gets `start_new_session=True`, so `kill` can terminate the process group and
  a crashed host cannot leave an orphan holding the GPU lock.
- The lock is a JSON file holding a pid; a dead pid is reaped on the next read, and so is a
  lock whose holder job already reached a terminal state (pid reuse cannot wedge the host).

## Write refusals

`klieg_publish` and `klieg_colour action=write` refuse to write under `/etc`, `/usr`, `/bin`,
`/sbin`, `/boot`, `/dev`, `/proc`, `/sys`, `/lib`, `/opt`, `/var/lib`, and under `~/.ssh`,
`~/.aws`, `~/.gnupg`, `~/.config/hermes`, `~/.hermes`. Paths are expanded (`~`) and resolved
before the check. This is not a sandbox — it is a guard against a mistyped path being obeyed.

## Logs

Each job's stdout/stderr goes to `plugin-data/klieg/jobs/<job>/log.txt`, capped at 8 MiB
(head truncated, tail kept) so a runaway loop cannot fill a disk. Logs contain whatever the
DCC prints — typically scene paths, frame numbers, and render times. They do **not** contain
the environment, because the environment is allow-listed.

## The live bridge

A bridge is a privileged surface, so its shape matters more than its features.

- **Unix socket, mode 0600, in the user's runtime directory.** Never TCP, never a fixed port,
  never world-readable. Another local user cannot connect.
- **No privilege gain.** The server runs inside a Blender the user started; executing code
  there is what opening any `.blend` and pressing Run Script already does.
- **`eval` is the only dangerous verb**, it is approval-gated at the tool layer like every other
  executing verb, and the namespace it receives starts as `{"bpy": bpy}` so nothing is imported
  implicitly.
- **A busy host is not a dead host.** The client distinguishes `BridgeTimeout` (connected,
  silent — Blender is modal) from `BridgeUnavailable` (nothing listening). Neither hangs the
  agent.
- **The GUI add-on parks requests in a queue** and executes them on Blender's main thread from
  a `bpy.app.timers` callback. A socket thread calling `bpy` directly is how you get random UI
  segfaults, which look like the plugin's fault.

## What is NOT protected

- **A script you approve is arbitrary code.** `klieg_run` executes Python inside a host that
  has your file permissions. Approving a call is approving that code. Read the script.
- **A malicious scene file can execute on open.** That is the DCC's behaviour, not Klieg's;
  `klieg_render` will open whatever blend you point it at.
- **No sandbox, no container, no privilege drop.** Klieg runs as you, with your `HOME` and
  your filesystem. Use a disposable machine or a scratch user for untrusted scenes. This
  matches the official `blender` plugin's own warning about its MCP bridge.
- **Approval policy is only as good as the caller.** Cron and other unattended contexts fail
  closed; an interactive session will show the prompt and wait.

## Reporting

Open an issue at <https://github.com/LangerSword/hermes-klieg/issues> with the tool name, the
arguments, and what happened. Please redact paths and any scene content you consider private.
