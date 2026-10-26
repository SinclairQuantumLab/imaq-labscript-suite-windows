"""Compile Labscript pseudoclock ``clock`` metadata into compact tick segments."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import labscript_utils.h5_lock  # noqa: F401  # Must be imported before h5py in labscript processes.
import h5py
import numpy as np
from labscript import ClockLine, LabscriptError
from qm import qua
from qm.qua._dsl.stream_processing.stream_processing import ResultStreamSource
from qm.qua._expressions import QuaVariable
from user_devices.opx.tick_playback_types import (
    InlineTickCommand,
    PlaybackControlMode,
    PlaybackSection,
    TickSegment,
    normalise_playback_sections,
)

QUA_WAIT_MAX_CYCLES = (1 << 28) - 1
QUA_VARIABLE_WAIT_MAX_CYCLES = (1 << 24) - 1
"""Conservative limit for a variable-duration wait on the tested OPX1000.

On QOP 3.8.1, hardware probes preserved large integer products but executed
``wait(variable)`` with the duration modulo 2**24. Literal waits did not wrap.
See ``diagnostics/runtime_wait_timing_probe.py`` for the isolated reproduction.
Bound the scaled result, not just the unscaled input, below this boundary.
"""
MAX_RUNTIME_TIME_DILATION = 8.0
"""Largest supported runtime ``fixed`` time-dilation multiplier."""


def seconds_to_cycles(
    values_s: float | Sequence[float], clock_cycle_s: float
) -> int | np.ndarray:
    """Convert seconds to integer OPX clock cycles, rounding to the 4 ns grid."""
    values = np.asarray(values_s, dtype=np.float64)
    cycles = np.rint(values / clock_cycle_s).astype(np.int64)
    if np.ndim(values) == 0:
        return int(cycles)
    return cycles


def build_tick_segments_from_clock(
    clock: Sequence[object],
    clock_line: ClockLine,
    clock_cycle_s: float,
) -> list[TickSegment]:
    """Convert ``Pseudoclock.clock`` entries for one clockline into tick segments."""
    segments: list[TickSegment] = []
    for entry in clock:
        if entry == "WAIT" or not isinstance(entry, dict):
            continue
        clock_entry = cast("dict[str, Any]", entry)
        enabled_clocks = clock_entry.get("enabled_clocks", [])
        if clock_line not in enabled_clocks:
            continue

        start_s = float(clock_entry["start"])
        reps = int(clock_entry["reps"])
        step_s = float(clock_entry["step"])
        if reps <= 0:
            continue

        step_cycles = int(seconds_to_cycles(step_s, clock_cycle_s))
        segments.append(
            TickSegment(
                start_s=start_s,
                reps=reps,
                step_cycles=step_cycles,
            )
        )
    return segments


def _segment_end_s(segment: TickSegment, clock_cycle_s: float) -> float:
    if segment.reps <= 1:
        return segment.start_s
    return segment.start_s + (segment.reps - 1) * (segment.step_cycles * clock_cycle_s)


def build_section_tick_plans(
    clock: Sequence[object],
    clock_line: ClockLine,
    playback_sections: Sequence[PlaybackSection],
    stop_time: float,
    inline_commands: Sequence[InlineTickCommand],
    *,
    default_time_dilation: float,
    control_mode: PlaybackControlMode,
    clock_cycle_s: float,
) -> dict[str, list[TickSegment]]:
    """Map compiled clock segments onto inline playback section names."""
    normalized_sections = normalise_playback_sections(
        playback_sections,
        stop_time,
        default_time_dilation=default_time_dilation,
        control_mode=control_mode,
        clock_resolution=clock_cycle_s,
    )
    if not normalized_sections:
        return {}

    terminal_stop_s = float(normalized_sections[-1].stop)
    all_segments = build_tick_segments_from_clock(clock, clock_line, clock_cycle_s)
    filtered_segments: list[TickSegment] = []
    for segment in all_segments:
        if (
            segment.reps == 1
            and abs(segment.start_s - terminal_stop_s) <= clock_cycle_s / 2
        ):
            continue
        filtered_segments.append(segment)

    section_by_name = {section.name: section for section in normalized_sections}
    plans: dict[str, list[TickSegment]] = {}
    for command in inline_commands:
        section = section_by_name.get(command.section_name)
        if section is None:
            raise LabscriptError(
                f"OPX inline tick playback command references unknown section "
                f"'{command.section_name}'."
            )
        section_segments: list[TickSegment] = []
        cursor_s = float(section.start)
        for segment in filtered_segments:
            segment_end_s = _segment_end_s(segment, clock_cycle_s)
            if segment_end_s < section.start - clock_cycle_s / 2:
                continue
            if segment.start_s >= section.stop - clock_cycle_s / 2:
                break
            first_wait_cycles = int(
                seconds_to_cycles(max(segment.start_s - cursor_s, 0.0), clock_cycle_s)
            )
            section_segments.append(
                segment.model_copy(update={"first_wait_cycles": first_wait_cycles})
            )
            cursor_s = max(cursor_s, segment_end_s)
        plans[command.section_name] = section_segments
    return plans


def _max_scaled_wait_base_cycles(time_dilation: QuaVariable | float) -> int:
    """Return a base chunk that stays wait-safe after time scaling."""
    if isinstance(time_dilation, float):
        max_scale = max(abs(float(time_dilation)), 1.0)
        wait_limit = QUA_WAIT_MAX_CYCLES
    else:
        max_scale = MAX_RUNTIME_TIME_DILATION
        wait_limit = QUA_VARIABLE_WAIT_MAX_CYCLES
    return max(4, int(wait_limit // max_scale))


def _emit_scaled_wait_chunk(
    base_cycles: int,
    time_dilation: QuaVariable | float,
    element: str,
    wait_cycles: QuaVariable[int],
    subtract_cycles: int,
) -> None:
    """Emit one bounded ``base_cycles * time_dilation - subtract_cycles`` wait.

    ``base_cycles`` is pre-sized by :func:`qua_wait_scaled_cycles` so that
    ``base_cycles * max_time_dilation`` always stays within
    the applicable literal- or variable-wait limit. A single ``qua.wait()`` is
    therefore always sufficient; no runtime ``while_`` chunk loop is emitted.
    Avoiding that loop keeps the real-time program shallow enough for QOP to
    compile when a section replays many ticks (for example a long ramp) under a
    runtime time dilation.
    """
    if base_cycles <= 0:
        return

    if isinstance(time_dilation, float):
        scaled_cycles = round(base_cycles * time_dilation) - int(subtract_cycles)
        if scaled_cycles >= 4:
            qua.wait(scaled_cycles, element)
        return

    qua.assign(
        wait_cycles,
        qua.Cast.mul_int_by_fixed(int(base_cycles), time_dilation)
        - int(subtract_cycles),
    )
    with qua.if_(wait_cycles >= 4):
        qua.wait(wait_cycles, element)


def qua_wait_scaled_cycles(
    base_cycles: int,
    time_dilation: QuaVariable | float,
    element: str,
    wait_cycles: QuaVariable[int],
    subtract_cycles: int = 0,
) -> None:
    """Emit ``wait(base_cycles * time_dilation - subtract_cycles)`` safely.

    QOP can fail internally when a large integer literal is multiplied by a
    runtime ``fixed`` variable. Split the literal first, scale each smaller
    chunk, and then apply the small pulse-duration correction once. Runtime
    chunks are sized so ``chunk * MAX_RUNTIME_TIME_DILATION`` still fits below
    :data:`QUA_VARIABLE_WAIT_MAX_CYCLES`, so each chunk emits exactly one
    ``qua.wait()`` without an additional runtime chunk loop.
    """
    if base_cycles <= 0:
        return

    base_chunk_cycles = _max_scaled_wait_base_cycles(time_dilation)
    num_full_chunks, remainder_cycles = divmod(int(base_cycles), base_chunk_cycles)

    if remainder_cycles == 0 and num_full_chunks > 0:
        remainder_cycles = base_chunk_cycles
        num_full_chunks -= 1

    if num_full_chunks == 1:
        _emit_scaled_wait_chunk(
            base_chunk_cycles,
            time_dilation,
            element,
            wait_cycles,
            0,
        )
    elif num_full_chunks > 1:
        repeat_index = qua.declare(int)
        with qua.for_(
            repeat_index, 0, repeat_index < num_full_chunks, repeat_index + 1
        ):
            _emit_scaled_wait_chunk(
                base_chunk_cycles,
                time_dilation,
                element,
                wait_cycles,
                0,
            )

    if remainder_cycles > 0:
        _emit_scaled_wait_chunk(
            remainder_cycles,
            time_dilation,
            element,
            wait_cycles,
            int(subtract_cycles),
        )


def emit_segment_tick_qua_precomputed_step(
    segments: Sequence[TickSegment],
    *,
    tick_element: str,
    tick_operation: str,
    tick_pulse_cycles: int,
    base_step_cycles: int,
    scaled_step_cycles: QuaVariable[int],
    scaled_step_minus_pulse_cycles: QuaVariable[int],
    tick_timestamp_stream: ResultStreamSource | None = None,
    tick_value_stream: ResultStreamSource | None = None,
) -> None:
    """Emit ticks using precomputed runtime integer wait variables.

    This path intentionally keeps ``qua.wait(variable, ...)`` but avoids
    ``Cast.mul_int_by_fixed`` entirely. It is intended for dense sections whose
    runtime dilation is selected from known discrete values. The caller assigns
    the scaled wait variables in QUA branches before calling this helper.
    """
    if not segments:
        return

    base_step_cycles = int(base_step_cycles)
    if base_step_cycles <= 0:
        raise LabscriptError(
            "Precomputed-step tick playback requires a positive base step."
        )

    def emit_tick() -> None:
        if tick_timestamp_stream is not None and tick_value_stream is not None:
            qua.play(
                tick_operation,
                tick_element,
                timestamp_stream=tick_timestamp_stream,
            )
            qua.save(1, tick_value_stream)
        else:
            qua.play(tick_operation, tick_element)

    def wait_precomputed(base_cycles: int, wait_cycles: QuaVariable[int]) -> None:
        if base_cycles <= 0:
            return
        repeats, remainder = divmod(int(base_cycles), base_step_cycles)
        if remainder:
            raise LabscriptError(
                "Precomputed-step tick playback can only scale waits that are "
                f"integer multiples of {base_step_cycles} cycles; got {base_cycles}."
            )
        if repeats == 1:
            with qua.if_(wait_cycles >= 4):
                qua.wait(wait_cycles, tick_element)
        elif repeats > 1:
            repeat_index = qua.declare(int)
            with (
                qua.for_(repeat_index, 0, repeat_index < repeats, repeat_index + 1),
                qua.if_(wait_cycles >= 4),
            ):
                qua.wait(wait_cycles, tick_element)

    tick_index = qua.declare(int)
    for segment in segments:
        wait_precomputed(int(segment.first_wait_cycles), scaled_step_cycles)

        reps = int(segment.reps)
        if reps <= 1:
            emit_tick()
            continue

        if int(segment.step_cycles) != base_step_cycles:
            raise LabscriptError(
                "Precomputed-step tick playback requires one segment step size; "
                f"expected {base_step_cycles}, got {segment.step_cycles}."
            )

        with qua.for_(tick_index, 0, tick_index < reps, tick_index + 1):
            with (
                qua.if_(tick_index > 0),
                qua.if_(scaled_step_minus_pulse_cycles >= 4),
            ):
                qua.wait(scaled_step_minus_pulse_cycles, tick_element)
            emit_tick()


def emit_segment_tick_qua(
    segments: Sequence[TickSegment],
    *,
    tick_element: str,
    tick_operation: str,
    tick_pulse_cycles: int,
    time_dilation: QuaVariable | float,
    tick_timestamp_stream: ResultStreamSource | None = None,
    tick_value_stream: ResultStreamSource | None = None,
) -> None:
    """Emit QUA waits and tick pulses for one section's segment plan."""
    if not segments:
        return

    wait_cycles = qua.declare(int)
    interval_cycles = qua.declare(int)
    pulse_cycles = int(tick_pulse_cycles)

    def emit_tick() -> None:
        if tick_timestamp_stream is not None and tick_value_stream is not None:
            qua.play(
                tick_operation,
                tick_element,
                timestamp_stream=tick_timestamp_stream,
            )
            qua.save(1, tick_value_stream)
        else:
            qua.play(tick_operation, tick_element)

    for segment_index, segment in enumerate(segments):
        if segment.first_wait_cycles > 0:
            # Segment offsets are measured between rising edges. After the
            # first segment, the previous pulse has already consumed its high
            # time on this element's timeline. Subtract it after scaling so
            # segment boundaries have the same timing as edges within a ramp.
            qua_wait_scaled_cycles(
                int(segment.first_wait_cycles),
                time_dilation,
                tick_element,
                wait_cycles,
                subtract_cycles=pulse_cycles if segment_index else 0,
            )

        reps = int(segment.reps)
        if reps <= 1:
            emit_tick()
            continue

        step_cycles = int(segment.step_cycles)
        tick_index = qua.declare(int)

        if isinstance(time_dilation, float):
            # Compile-time dilation: the inter-tick wait is a constant that QOP
            # folds, so emit it directly each iteration (the fixed-dilation
            # example compiles and runs this way).
            with qua.for_(tick_index, 0, tick_index < reps, tick_index + 1):
                with qua.if_(tick_index > 0):
                    qua_wait_scaled_cycles(
                        step_cycles,
                        time_dilation,
                        tick_element,
                        wait_cycles,
                        subtract_cycles=pulse_cycles,
                    )
                emit_tick()
            continue

        # Runtime dilation: every rep in this segment shares ``step_cycles``, so
        # the scaled inter-tick wait is identical for all of them. Compute it
        # ONCE before the loop. Recomputing ``mul_int_by_fixed`` inside the loop
        # makes QOP unroll heavy real-time arithmetic and fail to compile for
        # long ramps (hundreds of ticks).
        base_chunk_cycles = _max_scaled_wait_base_cycles(time_dilation)
        if step_cycles <= base_chunk_cycles:
            # ``step_cycles * MAX_RUNTIME_TIME_DILATION`` fits below
            # ``QUA_VARIABLE_WAIT_MAX_CYCLES`` and within the int range of
            # ``mul_int_by_fixed``, so the precomputed interval needs no chunking.
            qua.assign(
                interval_cycles,
                qua.Cast.mul_int_by_fixed(step_cycles, time_dilation) - pulse_cycles,
            )
            with qua.for_(tick_index, 0, tick_index < reps, tick_index + 1):
                with qua.if_(tick_index > 0), qua.if_(interval_cycles >= 4):
                    qua.wait(interval_cycles, tick_element)
                emit_tick()
            continue

        # Rare: a single inter-tick interval is long enough that it must be
        # chunked even at runtime. Fall back to per-iteration scaling, which
        # keeps every individual ``wait`` and ``mul_int_by_fixed`` in range.
        with qua.for_(tick_index, 0, tick_index < reps, tick_index + 1):
            with qua.if_(tick_index > 0):
                qua_wait_scaled_cycles(
                    step_cycles,
                    time_dilation,
                    tick_element,
                    wait_cycles,
                    subtract_cycles=pulse_cycles,
                )
            emit_tick()


def write_tick_segments_hdf5(
    playback_group: h5py.Group,
    section_plans: dict[str, list[TickSegment]],
    inline_commands: Sequence[InlineTickCommand],
) -> None:
    """Persist section tick segment plans under ``TICK_PLAYBACK/SEGMENTS``."""
    segments_group = playback_group.create_group("SEGMENTS")
    for command in inline_commands:
        section_group = segments_group.create_group(f"{command.index:04d}")
        section_group.attrs["clock_line_name"] = command.clock_line_name
        section_group.attrs["section_name"] = command.section_name
        plan = section_plans.get(command.section_name, [])
        section_group.attrs["num_segments"] = len(plan)
        if not plan:
            continue
        section_group.create_dataset(
            "start_s",
            data=np.asarray([segment.start_s for segment in plan], dtype=np.float64),
        )
        section_group.create_dataset(
            "reps",
            data=np.asarray([segment.reps for segment in plan], dtype=np.int64),
        )
        section_group.create_dataset(
            "step_cycles",
            data=np.asarray([segment.step_cycles for segment in plan], dtype=np.int64),
        )
        section_group.create_dataset(
            "first_wait_cycles",
            data=np.asarray(
                [segment.first_wait_cycles for segment in plan], dtype=np.int64
            ),
        )


def read_section_tick_plans_hdf5(
    playback_group: h5py.Group,
    inline_commands: Sequence[InlineTickCommand],
) -> dict[str, list[TickSegment]]:
    """Load section tick segment plans written by :func:`write_tick_segments_hdf5`."""
    segments_group = playback_group.get("SEGMENTS")
    if segments_group is None:
        return {}

    plans: dict[str, list[TickSegment]] = {}
    for command in inline_commands:
        section_group = segments_group.get(f"{command.index:04d}")
        if section_group is None:
            plans[command.section_name] = []
            continue
        num_segments = int(section_group.attrs.get("num_segments", 0))
        if num_segments == 0:
            plans[command.section_name] = []
            continue
        plans[command.section_name] = [
            TickSegment(
                start_s=float(start_s),
                reps=int(reps),
                step_cycles=int(step_cycles),
                first_wait_cycles=int(first_wait),
            )
            for start_s, reps, step_cycles, first_wait in zip(
                section_group["start_s"][()],
                section_group["reps"][()],
                section_group["step_cycles"][()],
                section_group["first_wait_cycles"][()],
            )
        ]
    return plans
