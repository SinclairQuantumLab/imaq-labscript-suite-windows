# Labscript OPX Driver

`user_devices.opx` is the reusable Labscript device package for Quantum Machines
OPX hardware. One `OPX` class covers both deployment roles below; BLACS behaviour
is selected with :meth:`~user_devices.opx.labscript_devices.OPX.set_execution_mode`.

## Deployment Roles

| Role | When to use | Reference apparatus |
|------|-------------|---------------------|
| **Master pseudoclock** | OPX is the Labscript timing master; replay compiled ticks from QUA | `connection_table.py` → `opx_main` |
| **Triggered segment runner** | External master owns shot timeline; OPX runs QUA released by TTL via one precompiled program with multiple `triggered_segment(...)` blocks per shot. | `connection_table_queued_triggered.py` → `opx_triggered` |

Tick playback (`enable_inline_tick_playback`, `qua_section`) applies to the
master role only.

## Public Modules

**Labscript / BLACS surface:**

- `register_classes.py` — Labscript device registry entry point (`user_devices.opx.register_classes`)
- `labscript_devices.py` — `OPX`, `OPXPseudoclock`, `OPXManualChannel`, `OPXInlineTickPlayback`, `OPXResultTrace`
- `qua_tick_programs.py` — experiment-facing `qua_section()` and tick-only fallback builder
- `qua_triggered_segments.py` — experiment-facing `triggered_segment()` for single-program, multi-trigger triggered OPX
- `qua_manual_programs.py` — generic config-derived BLACS manual-mode QUA builder and knob naming helpers
- `blacs_tabs.py` — `OPXTab` front panel (one widget group per `OPXManualChannel`, Start/Stop/Reset)
- `blacs_workers.py` — `OPXWorker`: shot HDF5 load, QUA execution, input-stream push, result export
- `execution_mode.py` — `execute` / `precompiled_program_id`
- `runviewer_parsers.py` — digital traces and OPX results for Runviewer

**Compile-time / HDF5 helpers:**

- `config_serialization.py` — tagged JSON bytes for `qua_config` in shot HDF5
- `tick_segment_compile.py` — Labscript pseudoclock metadata → compact QUA tick segments
- `tick_playback_types.py` — HDF5 playback schema models
- `shot_stream_metadata.py` — HDF5 read/write for `INPUT_STREAMS/` and `execution_mode`
- `precompiled_job.py` — QM `compile()`/`add_compiled()`
- `result_io.py` — `RESULTS/` HDF5 read/write contract

**Runtime helpers (used by worker / tests):**

- `opx_job_runner.py` — `OpxJobRunner`: compile, arm, and start jobs from shot HDF5
- `opx_shot_loader.py` — parse shot HDF5 into worker-ready structures
- `opx_job_status.py` — `read_job_status()`, `job_has_finished()`, QOP 2.x vs 3.x normalization
- `opx_result_exporter.py` — fetch QM handles and write `RESULTS/`
- `opx_export_lock.py` — cross-process lock for concurrent result export
- `opx_headless_runner.py` — hardware-free shot replay without BLACS (tests, CI)
- `qua_program_print.py` — optional QUA program pretty-printing for debugging

## Master Pseudoclock Pattern

Use `OPX.enable_inline_tick_playback()` with
`user_devices.opx.qua_tick_programs.qua_section()` and
`OPX.set_qua_program_builder()` on a master OPX (no `trigger_device`):

```python
from user_devices.opx.qua_tick_programs import qua_section

playback = opx.enable_inline_tick_playback(
    tick_element="pseudoclock_tick_line_fast",
    tick_operation="emit_tick",
    timestamp_stream_name="opx_fast_pseudoclock_tick_timestamps",
)


def build_opx_qua_program():
    with qua.program() as program:
        playback.qua_prepare_tick_playback()
        with qua_section(opx, "measurement", t, duration_s=1.0, playback=playback):
            ...
        with qua.stream_processing():
            playback.save_tick_trace()
    return program


opx.set_qua_program_builder(build_opx_qua_program)
```

### Tick-only fallback (master role)

For timing smoke tests with no measurement QUA, call
`opx.enable_tick_playback(...)` (or `enable_inline_tick_playback`) **without**
`set_qua_program_builder`. BLACS builds a tick-only QUA program from
`TICK_PLAYBACK/CLOCK_LINES/` at runtime. See
`experiment_multi_clock_lines_tick_only.py`. Tick-only mode rejects
`qua_logic` time-dilation sections.

### `OPXResultTrace`

`OPXResultTrace` is a Labscript placeholder channel — it does not drive hardware
directly. Register the actual QUA result with `opx.add_result_trace(...)` in
the experiment builder; BLACS exports values under `RESULTS/<trace_name>/` after
the job completes. Parent the trace to an intermediate device on the relevant
clock line so Runviewer knows which pseudoclock timeline it belongs to.

## Execution Modes

BLACS reads `execution_mode` from each compiled shot HDF5 file. Modes describe
**how many QUA programs** run and **whether they are recompiled each shot** — not
whether the OPX is the Labscript master. A triggered OPX (`trigger_device` set)
can use any mode; its QUA program should start with `wait_for_trigger(...)` so
the external master releases execution.

On a triggered OPX, BLACS arms the job during `transition_to_buffered` rather
than `start_run`.

### `execute` (default)

Every shot calls `qm.execute(program)`, recompiling the stored QUA program on
the cluster. Typical for master `opx_main` development; also valid for a
single triggered program.

### `precompiled_program_id` (single program)

Compile the QUA program once per BLACS session, cache the returned
`program_id`, and start each shot with `add_compiled(program_id)`. Shot-varying
scalars must use QUA input streams:

```python
opx.set_execution_mode("precompiled_program_id")
opx.set_qua_program_builder(build_opx_qua_program)

detuning_mhz = globals()["detuning_mhz"]
opx.set_input_stream_values({"detuning": detuning_mhz})
```

On a **triggered** OPX, the builder should still open with
`qua.wait_for_trigger(...)`; the master sends one TTL when Labscript calls
`opx.trigger(...)`.

Requirements:

- Fixed QUA program structure for the whole BLACS session.
- Shot-varying values through input streams, not Python constants baked in at compile time.
- Per-shot values in `INPUT_STREAMS/` HDF5; BLACS pushes them before each job.

Tick time-dilation input streams work in both execution modes (master role only).

### Single program, multiple triggered segments (`precompiled_program_id`) — triggered role

For an external master (ADwin, PulseBlaster, etc.) plus a secondary OPX, the
**recommended** pattern is:

- Run Manager owns scan/repeat → **one Labscript shot per point**.
- **One QUA program** per BLACS session (`precompiled_program_id`), with
  several `triggered_segment(...)` blocks inside it.
- Per-shot scalars (and small fixed-length arrays) via input streams.

See `experiment_triggered_multi_segment_precompiled.py` for the full worked
example (handshake + Run Manager global `probe_detuning_mhz`).

`user_devices.opx.qua_triggered_segments.triggered_segment()` wraps the
`wait_for_trigger`/`align` bookkeeping each segment needs:

```python
from user_devices.opx.qua_triggered_segments import triggered_segment

def build_program():
    with qua.program() as prog:
        with triggered_segment(opx_triggered, "cooling", "master_trigger"):
            ...
        with triggered_segment(opx_triggered, "probe", "master_trigger"):
            ...
    return prog

opx_triggered.set_execution_mode("precompiled_program_id")
opx_triggered.set_qua_program_builder(build_program)
opx_triggered.set_input_stream_values({
    "probe_detuning_hz": int(round(probe_detuning_mhz * 1e6)),
    ...
})
```

Master Labscript timeline calls (`start()`, `opx_triggered.trigger()`,
`wait()`, digital outputs, and so on) can live **inside the same builder** next
to each `triggered_segment(...)` block so the shot reads top-to-bottom. Labscript
calls are compile-time Python; only `qua.*` becomes QUA. See
`experiment_triggered_multi_segment_precompiled.py` for the full pattern (`stop(t)`
only remains outside the builder).

Input streams accept scalars (`bool`, `int`, `float`) and Python lists up to
64 entries (`int` or `float` arrays) for shot-varying small schedules.

## BLACS Manual Mode (triggered secondary only)

Manual control is for a **triggered** OPX (`trigger_device` set), not the master
pseudoclock. Declare one or more inert `OPXManualChannel` children on the OPX in
the connection table; they contribute no Labscript instructions and are invisible
to pseudoclock expansion:

```python
from user_devices.opx.labscript_devices import OPX, OPXManualChannel

manual_tone = OPXManualChannel(
    "manual_tone_channel",
    parent_device=opx_triggered,
    element="manual_tone",  # QM config element name
    operations=["cw"],  # keys under element["operations"]
    kind=OPXManualChannel.KIND_SINGLE_INPUT,  # panel label metadata only
)
```

After BLACS starts, `OPXTab` builds a front-panel group per channel (gate,
operation dropdown, frequency, amplitude, phase, duration). Knob names match QUA
input streams via `qua_manual_programs.input_stream_name(channel_name, knob)` (string channel name, not the device object).

**Prerequisites:** run at least one buffered shot that stores `qua_config` in the
HDF5 device group — manual mode compiles against that config. The reference
shot is `experiment_manual.py` (`CONFIG_OPX1000_MANUAL`). Until then,
Start does nothing useful.

**Runtime:** `OPXWorker.start_manual_program()` compiles (or reuses) a generic
infinite-loop QUA program once per BLACS session, runs it as an out-of-shot job,
and a background thread re-pushes all knob values every 100 ms so QUA
`advance_input_stream` calls can keep iterating. `program_manual` only records
desired values; it does not push directly. Stop clears a `_manual_program_wanted`
flag so the job stays off after the next shot; otherwise manual mode auto-resumes
in `transition_to_manual`.

**Overrides:** subclass `OPXWorker.build_manual_qua_program(...)` for non-generic
manual QUA (e.g. homogenization routines), or subclass `OPXTab.create_manual_channel_widgets()`
for a custom panel. Declare one `OPXManualChannel` per QM element.

Worker hooks also used by apparatus calibration code:
`start_out_of_shot_compiled_job`, `stop_out_of_shot_job`, `apply_qm_config_overlay`.

Release code should import QUA helpers from
`user_devices.opx.qua_tick_programs`. The old apparatus-level helper module is
intentionally not shipped.

## Production Defaults

- The `OPX` constructor does not open a live `QuantumMachinesManager`; BLACS does that at shot runtime.
- QM config payloads are stored as tagged JSON bytes under `qua_config` (via `config_serialization.py`).
- Legacy `str(dict)` shot files are not supported by this clean release; recompile shots to write tagged JSON config data.
- QUA program printing is disabled by default; enable via `qua_program_print` helpers for debugging only.
- Worker QMM logging defaults to `WARNING`.
- Job completion normalization lives in `opx_job_status.py` (`read_job_status()`, `job_has_finished()`, `job_ready_for_export()`), used by `blacs_workers.py`, `opx_job_runner.py`, and `opx_headless_runner.py`.

## Known Limits

- All emitted timing must fit the 4 ns OPX grid.
- Inline playback defaults to a bounded section command buffer; increase `max_inline_sections` deliberately for larger programs.
- Runtime `qua_logic` choices are intentionally not rewritten into static HDF5 section metadata.
- Multi-OPX trigger chaining needs a complete hardware example before it is considered stable.
- Triggered `precompiled_program_id`, handshake, and manual mode are compile-tested; extend hardware validation on your apparatus before production use.
- The device still imports private QM typing/DSL symbols where the public SDK does not expose equivalent type hints. Treat the tested `qm-qua` version range as part of the release contract.
- `opx_headless_runner.py` replays shot HDF5 without BLACS for tests; it does not replace hardware validation.
