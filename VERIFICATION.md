# Verification

What was run, on what machine, with what result. Anything not listed here is **not**
verified — including the parts that sound impressive.

## Environment

| | |
|---|---|
| OS | Arch Linux, kernel 7.3.4, x86-64 |
| Python | 3.14.10 (system) |
| Hermes | plugin host, `plugins.isolation: host` |
| Blender | 5.3.0 at `/usr/bin/blender` |
| Houdini / Nuke / C4D / AE / Resolve | **not installed** — adapters report `found: false` |
| GPU | not used by this suite; no render is executed in tests |

## Test suite

Command, from the repository root:

```
python3 -W error::ResourceWarning -m unittest discover -s tests
```

The declared Python dependencies must be installed first (`numpy>=1.26,<3`,
`Pillow>=10,<12`); CI installs them in `.github/workflows/tests.yml`.

Last full run on this branch (Arch Linux, Python 3.11, Blender 5.3 available):

```
Ran 70 tests in 13.724s

OK
```

70 tests, no skips, no warnings. The suite is hermetic: it sets
`HERMES_PLUGIN_DATA` to a fresh temp dir, so a previous run's history cannot change an
assertion. Blender is not required: tests that need a DCC stub its adapter. Coverage by guarantee:

| guarantee | test |
|---|---|
| a job completes and verifies against its artefact | `test_detached_job_completes_and_verifies` |
| **a stale artefact is not success** | `test_stale_artefact_is_not_success` |
| a missing artefact is not success | `test_missing_artefact_is_not_success` |
| **a partial render does not verify** | `test_partial_output_does_not_verify` |
| a failing job keeps its exit code | `test_failure_keeps_exit_code` |
| kill marks the job and releases the GPU lock | `test_kill_marks_job_and_releases_lock` |
| an unknown job id is reported, never raised | `test_unknown_job_is_reported_not_raised` |
| the GPU lock excludes and cannot be stolen | `test_second_holder_refused` |
| a dead holder's lock is reaped | `test_dead_holder_is_reaped` |
| frame specs parse (ranges, lists, whitespace) | `FramesParser` (2) |
| every declared tool has a schema and handler | `test_every_declared_tool_has_schema_and_handler` |
| probe returns every adapter | `test_probe_returns_json_with_adapters` |
| bad tool input returns an error, not a traceback | `test_jobs_status_without_job_is_an_error`, `test_publish_rejects_missing_dir_without_crashing` |
| unknown DCC raises a typed error | `test_unknown_dcc_raises_keyerror` |
| Blender argv is shaped as documented | `test_blender_argv_shape` |
| an unsupported host says so instead of pretending | `test_ae_declares_unsupported_instead_of_lying` |
| the launch PATH carries no user paths | `test_safe_env_has_no_user_paths` |
| **plan resolves files and argv without running** | `test_plan_resolves_expected_files` |
| plan reports blockers instead of guessing | `test_plan_reports_blockers_without_running` |
| plan rejects an unknown host | `test_plan_rejects_unknown_dcc` |
| **a second render queues, then starts when the lock frees** | `test_render_queues_behind_holder_then_runs` |
| `queue=false` refuses rather than stacking two renders | `test_queue_false_refuses_instead_of_stacking` |
| **agent secrets never reach a child process** | `test_agent_secrets_do_not_reach_children` |
| the allow-list keeps what a DCC needs | `test_allowlist_keeps_what_a_dcc_needs` |
| publish refuses system and credential paths | `test_publish_refuses_system_and_credential_paths` |
| **bridge client survives a silent host** | `test_silent_host_raises_timeout_not_hang` |
| bridge reports a host that dies mid-call | `test_host_closing_without_reply_is_reported` |
| bridge raises unavailable with no socket | `test_missing_socket_raises_unavailable` |
| colour diff catches a changed view transform | `test_compare_flags_a_view_transform_change` |
| colour manifest round-trips with the OCIO hash | `test_manifest_round_trip_and_ocio_hash` |
| taste features are numeric and separate frames | `test_features_are_numbers_and_differ_by_frame` |
| **taste refuses to score below 12 verdicts** | `test_refuses_to_score_without_verdicts` |
| taste trains and scores once there is signal | `test_trains_and_scores_once_there_is_signal` |

## Plugin admission

```
$ hermes plugins validate .
✓ manifest — plugin.yaml parses
✓ requires_hermes — spec '>=0.22.0' parses
✓ capability probe — register() ran in isolation
✓ declared tools — matches registrations
✓ declared hooks — matches registrations
✓ security scan — safe
✓ no core override — no runtime rebinds of Hermes core
Validation passed.

$ hermes plugins doctor .
manifest: klieg 0.1.0 (standalone)
OK: runtime discovery, manifest parsing, import, and registration passed
registrations: 9 tool(s), 1 hook(s)
```

## End-to-end, through the plugin

`scripts/e2e.py` drives the same code path the tools use: it renders two frames with
`klieg_render`, verifies them with `klieg_jobs verify`, then encodes with `klieg_publish`.

```
1. render 2 frames through klieg_render (25 %, 32 samples)
   job e2e-e2e548cf pid 1255397
   state: done exit: 0
2. verify: artefacts must be newer than the job
   ok: True artefacts: ['0000.png', '0001.png'] stale: 0 missing: 0
3. publish: BT.709 encode of what was just rendered
   state: done verify: True bytes: 20844

E2E OK
```

The output is committed: [`docs/media/e2e_ig.mp4`](docs/media/e2e_ig.mp4), 20,844 bytes,
rendered from a real scene at 25 % / 32 spp and encoded with the BT.709 conversion and
`h264_metadata` colour tags.

That run also caught a genuine bug the unit tests could not: libx264 with `yuv420p` refuses
odd dimensions, and a 25 % render of 540×960 is 135 px wide. `klieg_publish` now inserts
`scale=trunc(iw/2)*2:trunc(ih/2)*2` so a user never meets "width not divisible by 2".

## The live bridge, against a real Blender

`scripts/test_bridge.py` launches **Blender 5.3.0**, waits for the socket, and drives it through
the same `Bridge` class the tool uses:

```
PASS  blender started and bound the socket
PASS  ping                               pong
PASS  info reports a real Blender        5.3.0 objects=3 vt=AgX
PASS  eval mutates the scene             4 (was 3)
PASS  reads colour management            'AgX'
PASS  error comes back as data           ValueError surfaced
PASS  session survives a failed call     24
PASS  shutdown acknowledged              0.00s
PASS  process exited after shutdown      0
PASS  socket removed on exit
10/10 passed
```

The detail that matters: `vt=AgX` is the factory default, and the film project graded under
Khronos PBR Neutral. That single field is exactly what `klieg_colour action=compare` refuses to
let slide.

## Not verified — stated plainly

- **A full film was not rendered by this suite.** `klieg_render` launched a real 2-frame pass
  (see the end-to-end section) and the job lifecycle is exercised, but nothing here renders
  288 frames of Cycles output.
- **No live bridge exists yet.** `session()` returns `None`; 0.1 is batch only.
- **Non-Blender adapters are declarations.** `hython`, `nuke -t` and C4D are implemented
  from their documented CLIs but could not be run here — none of the hosts are installed.
  After Effects and Resolve are reported as present-but-unsupported rather than faked.
- **The queue was tested with shell sleepers, not two real Blender renders.** The lock
  arbitration, ordering and hand-off are covered; the interesting tail case — a Blender
  process that ignores SIGTERM and holds the lock past `kill` — is not.
- **The GUI add-on is written but not exercised here.** `blender/klieg_addon.py` registers, opens
  a 0600 socket and parks requests for the main thread, but this machine has no interactive
  Blender session to install it into. The headless server, which shares the protocol and the
  executor, is the one proven above.
- **The live bridge is Blender-only.** Houdini's `hrpyc`, Nuke's `-t` socket and AE's UXP are
  separate protocols, not configurations of this one.
- **Taste has never seen a real verdict.** The model is tested against synthetic separable
  frames; with zero recorded judgements it refuses to score, which is the honest default but
  also means its usefulness on a real film is unproven.
- **`klieg_publish` has encoded two frames, not a film.** The BT.709 conversion and the
  `h264_metadata` tags are exercised in `docs/media/e2e_ig.mp4`; a 288-frame pass with audio
  has not been run from this repo.

If a claim is not in the first three sections, treat it as unproven.
