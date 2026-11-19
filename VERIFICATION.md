# Verification

What was run, on what machine, with what result. Anything not listed here is **not**
verified — including the parts that sound impressive.

## Environment

| | |
|---|---|
| OS | Arch Linux, kernel 7.3.4, x86-64 |
| Python | 3.14.9 (system, bare-stdlib run); 3.12 venv with numpy 2.5.5 / Pillow 13.0.0 (full run) |
| Hermes | plugin host, `plugins.isolation: host` |
| Blender | 5.3.0 at `/usr/sbin/blender` |
| ffmpeg | 9.0.1 (encode, colour tags, frame counting) |
| Houdini / Nuke / C4D / AE / Resolve | **not installed** — adapters report `found: false` |
| GPU | not used by the suite; the e2e pass renders 2 frames at 25 % / 32 spp |

## Test suite

Command, from the repository root:

```
python3 -W error::ResourceWarning -m unittest discover -s tests
```

With the declared dependencies installed (`numpy>=1.26,<3`, `Pillow>=10`, plus
`playwright` + a chromium headless shell for the motion render test; CI installs the
first two in `.github/workflows/tests.yml`):

```
Ran 159 tests in 35.880s

OK (skipped=1)
```

On the bare system interpreter, without numpy/Pillow/playwright:

```
Ran 159 tests in 19.640s

OK (skipped=26)
```

The one skip in the full run is the PyYAML packaging check (PyYAML not installed); the 26
bare-run skips are the pixel-dependent tests and the live motion render, which skip cleanly
instead of erroring. The
suite is hermetic: it sets `HERMES_PLUGIN_DATA` to a fresh temp dir, so a previous run's
history cannot change an assertion. Blender is not required: tests that need a DCC stub its
adapter. Coverage by guarantee:

| guarantee | test |
|---|---|
| a job completes and verifies against its artefact | `test_detached_job_completes_and_verifies` |
| **a stale artefact is not success** | `test_stale_artefact_is_not_success` |
| a missing artefact is not success | `test_missing_artefact_is_not_success` |
| **a partial render does not verify** | `test_partial_output_does_not_verify` |
| a failing job keeps its exit code | `test_failure_keeps_exit_code` |
| **concurrent status writes do not collide on the tmp file** | `test_concurrent_writes_do_not_collide` |
| kill marks the job and releases the GPU lock | `test_kill_marks_job_and_releases_lock` |
| an unknown job id is reported, never raised | `test_unknown_job_is_reported_not_raised` |
| the GPU lock excludes and cannot be stolen | `test_second_holder_refused` |
| a dead holder's lock is reaped | `test_dead_holder_is_reaped` |
| **a terminal holder's lock is reaped even if its pid was reused** | `test_terminal_holder_lock_is_reaped_even_with_live_pid` |
| frame specs parse (ranges, lists, whitespace) | `FramesParser` (2) |
| **a frame spec cannot allocate a billion ints** | `test_frame_spec_cannot_allocate_a_billion_ints` |
| every declared tool has a schema and handler | `test_every_declared_tool_has_schema_and_handler` |
| probe returns every adapter | `test_probe_returns_json_with_adapters` |
| **bad input is data in every handler, never a traceback** | `StructuredErrors` (8 cases incl. unknown DCC, missing args, malformed numbers, timeouts) |
| bad input wins over a missing host | `test_bad_input_wins_over_missing_host` |
| Blender argv is shaped as documented | `test_blender_argv_shape` |
| an unsupported host says so instead of pretending | `test_ae_declares_unsupported_instead_of_lying`, `test_unsupported_render_adapter_is_data` |
| the launch PATH carries no user paths | `test_safe_env_has_no_user_paths` |
| **plan resolves files and argv without running or writing** | `test_plan_resolves_expected_files`, `test_dry_resolves_argv_without_writing` |
| plan reports blockers instead of guessing | `test_plan_reports_blockers_without_running` |
| plan rejects an unknown host | `test_plan_rejects_unknown_dcc` |
| **a second render queues through the TOOL, then runs** | `test_render_queues_behind_holder_through_the_tool` |
| `queue=false` refuses through the tool | `test_render_queue_false_refuses_through_the_tool` |
| **a busy host does not strand a free host's queue** | `test_free_host_advances_behind_busy_one` |
| kill hands the GPU to the next queued job | `test_kill_hands_gpu_to_next_queued_job` |
| **agent secrets never reach a child process** | `test_agent_secrets_do_not_reach_children` |
| the allow-list keeps what a DCC needs | `test_allowlist_keeps_what_a_dcc_needs` |
| publish refuses system and credential paths | `test_publish_refuses_system_and_credential_paths` |
| **a mid-sequence frame set encodes every frame** | `test_mid_sequence_encodes_all_frames` (real ffmpeg, decoded frame count) |
| **a gapped frame set encodes every frame, not up to the gap** | `test_gapped_set_encodes_all_frames` (real ffmpeg, decoded frame count) |
| **concurrent renders cannot overwrite each other's script** | `test_two_renders_get_distinct_scripts_with_their_own_frames` |
| a path with quotes/spaces cannot break the render script | `test_path_with_quotes_and_spaces_round_trips` |
| **bridge client survives a silent host** | `test_silent_host_raises_timeout_not_hang` |
| bridge reports a host that dies mid-call | `test_host_closing_without_reply_is_reported` |
| bridge raises unavailable with no socket | `test_missing_socket_raises_unavailable` |
| colour diff catches a changed view transform | `test_compare_flags_a_view_transform_change` |
| colour manifest round-trips with the OCIO hash | `test_manifest_round_trip_and_ocio_hash` |
| colour write resolves relative paths and refuses credential dirs | `test_relative_blend_write_does_not_crash`, `test_write_refuses_credential_dirs` |
| the batch colour probe is confined and cleaned up | `test_batch_probe_script_is_confined_and_cleaned` |
| the session colour probe survives apostrophes | `test_session_probe_survives_apostrophes` |
| dead sessions are pruned from the list | `test_list_prunes_dead_sessions` |
| **approval is per action, and the policy is tested** | `ApprovalPolicy` (6 cases) |
| taste features are numeric and separate frames | `test_features_are_numbers_and_differ_by_frame` |
| **taste refuses to score below 12 verdicts** | `test_refuses_to_score_without_verdicts` |
| taste trains and scores once there is signal | `test_trains_and_scores_once_there_is_signal` |
| **taste accuracy is held-out, not training** | `test_accuracy_is_held_out_not_training` |
| a one-verdict minority class is labelled unverified | `test_single_minority_verdict_is_labelled_unverified` |
| taste scoring refuses feature drift instead of crashing | `test_score_refuses_feature_drift_instead_of_crashing` |
| a dark 16-bit frame is not reported bright | `test_dark_16bit_frame_is_not_reported_bright` |
| **a sealed chain verifies intact** | `test_seal_check_intact_chain` |
| **a tampered/deleted/added frame is reported** | `test_tampered_frame_is_reported`, `test_deleted_and_added_frames_are_reported` |
| an edited scene or swapped colour manifest is reported | `test_edited_scene_is_reported`, `test_colour_manifest_is_part_of_the_seal` |
| a publish seal links back to its source frames | `test_publish_links_back_to_source_frames` |
| seal refuses a job that is not done | `test_seal_requires_a_done_job` |
| **flash gate fails a 6-flash/s sequence, passes a steady one** | `test_flash_alternating_black_white_fails_guideline`, `test_flash_steady_sequence_passes` |
| loop gate closes identical endpoints, opens different ones | `test_loop_identical_endpoints_close` |
| stats gate sees exposure drift and stability | `test_stats_detects_exposure_drift`, `test_stats_constant_exposure_is_stable` |
| safe_band finds detail parked in a UI margin | `test_safe_band_finds_detail_in_the_top_margin` |
| built-in gates are approval-free; script gates prompt | `test_builtin_gates_are_approval_free_script_gates_prompt` |
| **motion compiler emits a timeline + hook, splits kinetic type** | `CompileScene` (7), `Templates` (5) |
| motion render/preview gate, templates free; bad input is data | `MotionHandler` (7) |
| **a motion template renders to a verified MP4 through the tool** | `test_template_renders_to_verified_mp4` (real playwright + ffmpeg) |

## Plugin admission

```
$ hermes plugins validate .
✓ manifest — plugin.yaml parses
✓ requires_hermes — spec '>=0.22.0' parses
✓ capability probe — register() ran in isolation
✓ declared tools — matches registrations
✓ declared hooks — matches registrations
✓ security scan — caution
✓ no core override — no runtime rebinds of Hermes core
⚠ security scan caution: aws_dir_access, gpg_dir_access, ssh_dir_access (klieg_tools.py),
  python_os_environ (klieg.yaml)
Validation passed.

$ hermes plugins doctor .
OK: runtime discovery, manifest parsing, import, and registration passed
registrations: 14 tool(s), 1 hook(s)
```

The cautions are deliberate and documented, not suppressed: the `*_dir_access` hits are the
write **deny-list** in `klieg_tools.py` (paths Klieg refuses, see SECURITY.md), and the
catalog entry mentions `os.environ` to describe the allow-list that replaces it.

### Served-surface smoke

`validate`/`doctor` run `register()` in isolation but never drive the registered hook or a
handler. `smoke_load.py` closes that gap: it loads `__init__.py` as a package with relative
imports, registers against a recording context, then dispatches the real `pre_tool_call`
callback and a real handler. Stdlib only — no numpy/Pillow, no Blender, no plugin host. It
runs in CI on every OS/Python cell.

```
$ python3 smoke_load.py
version: 0.3.0
registered tools: 14 [...]
registered hooks: ['pre_tool_call']
hook klieg_render   {...frames 0-1...}      -> approve
hook klieg_probe    {}                      -> None
hook klieg_gate     {gate: flash, ...}      -> None
hook klieg_gate     {script: m.py}          -> approve
hook klieg_session  {action: status}        -> None
hook klieg_session  {action: eval, ...}     -> approve
hook klieg_ledger   {action: check, ...}    -> None
hook klieg_ledger   {action: seal, ...}     -> approve
hook klieg_motion   {action: templates}     -> None
hook klieg_motion   {action: render, ...}   -> approve
klieg_ledger check(no-such-job) -> {"ok": false, "error": "...no ledger; seal it first"}
klieg_motion templates -> ['title-reveal', 'lower-third', 'kinetic-quote', 'logo-sting']

LOAD SMOKE OK
```

## End-to-end, through the plugin

`scripts/e2e.py` drives the same code path the tools use: it renders frames 1-2 with
`klieg_render`, verifies them with `klieg_jobs verify`, then encodes with `klieg_publish`.
Frames 1-2 (Blender's native 1-based range) exercise publish's `-start_number` path.

```
1. render frames 1-2 through klieg_render (25 %, 32 samples)
   job e2e-f25fea17 pid 1173804
   state: done exit: 0
2. verify: artefacts must be newer than the job
   ok: True artefacts: ['0001.png', '0002.png'] stale: 0 missing: 0
3. publish: BT.709 encode of what was just rendered
   state: done verify: True bytes: 5573

E2E OK
```

The output is committed: [`docs/media/e2e_ig.mp4`](docs/media/e2e_ig.mp4), 5,573 bytes,
rendered from a real scene at 25 % / 32 spp and encoded with the BT.709 conversion and
`h264_metadata` colour tags.

History worth keeping: an earlier run caught a genuine bug the unit tests could not —
libx264 with `yuv420p` refuses odd dimensions, and a 25 % render of 540×960 is 135 px wide.
`klieg_publish` inserts `scale=trunc(iw/2)*2:trunc(ih/2)*2` so a user never meets "width not
divisible by 2". This run's predecessor caught two more: image2 only probes start numbers
0-4 (a 100-110 render failed outright), and a gapped set encoded one frame and reported
exit 0. Both are now fixed and tested with decoded frame counts.

## The live bridge, against a real Blender

`scripts/test_bridge.py` launches **Blender 5.3.0**, waits for the socket, and drives it through
the same `Bridge` class the tool uses:

```
PASS  blender started and bound the socket
PASS  ping                               pong
PASS  info reports Blender 4.2+          5.3.0 objects=3 vt=AgX
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

## The ledger and gates, against the real e2e job

After the e2e run, through the same CLI shim the tools use:

```
$ klieg_cli.py ledger seal --job e2e-f25fea17
{ "ok": true, "frames": 2,
  "ledger_root": "63a30c783e50903ac8ab7c0259bf2f4e64e3310d6bb87534f427a319834f4007",
  "scene": "0e56d65db75c18bb962c2d767c597517db0c527bfdbc159fc3551925f1a7052a" }

$ klieg_cli.py ledger check --job e2e-f25fea17
{ "ok": true, "intact": true, "changed": [], "missing": [], "added_frames": [],
  "source_frames_changed": false }

$ klieg_cli.py gate loop --frames /tmp/klieg-e2e/frames
{ "gate": "loop", "mean_abs_diff": 0.0, "loop_closed": true }

$ klieg_cli.py gate stats --frames /tmp/klieg-e2e/frames
{ "gate": "stats", "luma_mean": 0.26446, "temporal_std": 0.0, "exposure_drift": 0.0 }

$ klieg_cli.py gate flash --frames /tmp/klieg-e2e/frames --fps 24
{ "gate": "flash", "transitions": 0, "max_flashes_per_second": 0.0,
  "passes_guideline": true }
```

The scene is a static cube, so a closed loop at 0.0 difference and zero temporal drift are
the correct answers, not a coincidence. Tamper detection is exercised by the unit tests
against real files (changed, deleted, added frames; edited scene; swapped manifest).

One observed fact worth recording: Pillow 13 loads Blender's 16-bit RGBA PNGs as 8-bit
(`mode RGBA, dtype uint8`). Taste and the gates therefore measure 8-bit samples of those
frames; 16-bit **grayscale** (`I;16`) is scaled explicitly, because Pillow's
`convert("RGB")` clips it at 255 instead of scaling.

## Motion design, through the tool

`klieg_motion` was exercised end-to-end through the same CLI shim the tools use: a
title-reveal template compiled to HTML+GSAP and rendered frame-by-frame to MP4 as a
detached job, then verified.

```
$ klieg_cli.py motion preview --template title-reveal \
      --params '{"word":"KLIEG","tagline":"motion design for Hermes"}' --t 3
{ "preview": ".../motion/preview-7fe235fb.png", "t": 3.0, "width": 1920, "height": 1080 }

$ klieg_cli.py motion render --template title-reveal --params '{...}' \
      --out ~/.cache/klieg-motion/title.mp4 --format mp4
{ "job": "motion-40a45eaa", "state": "running" }

$ klieg_cli.py jobs verify --job motion-40a45eaa
{ "ok": true, "artefacts": [title.mp4], "stale": [], "missing": [] }

$ ffprobe title.mp4   ->  h264 1920x1080, duration 6.000000
```

The preview frame was visually inspected: KLIEG fully revealed in bold cream type, orange
rule, correct tagline, dark cinematic field, no serif fallback or overflow. The render is
deterministic (seek + screenshot per frame), so there are no screencast frame-drops.

## Not verified — stated plainly

- **A full film was not rendered by this suite.** `klieg_render` launched a real 2-frame pass
  (see the end-to-end section) and the job lifecycle is exercised, but nothing here renders
  288 frames of Cycles output.
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
- **The flash gate is a screening approximation.** It has not been compared against a
  certified Harding test on known flashing content.
- **The ledger is not a signature.** It detects drift between seal and check; it does not
  authenticate who produced the files.
- **Only the title-reveal template was rendered end-to-end.** The other templates
  (lower-third, kinetic-quote, logo-sting) and the declarative spec compiler are unit-tested
  (they compile to valid HTML+GSAP), but only title-reveal was driven through a full render
  here. The GIF output path is implemented but was not rendered live in this record.
- **Motion rendering needs playwright + a chromium headless shell.** Without them,
  render/preview report the missing dependency as data; the compiler and templates still work.

If a claim is not in the sections above, treat it as unproven.