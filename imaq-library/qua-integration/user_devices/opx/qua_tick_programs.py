"""Reusable QUA helpers for OPX pseudoclock tick playback.

This module is part of the reusable ``user_devices.opx`` package. It
contains both the experiment-facing ``qua_section()`` helper and the BLACS
tick-only fallback builder so the device driver has no dependency on a specific
``labscriptlib`` apparatus package.
"""

from collections.abc import Sequence
from contextlib import contextmanager

from labscript import LabscriptError
from qm import Program, qua
from qm.qua._dsl.stream_processing.stream_processing import ResultStreamSource
from qm.qua.type_hints import QuaVariable, QuaVariableInputStream
from user_devices.opx.labscript_devices import OPX, OPXInlineTickPlayback
from user_devices.opx.tick_playback_types import (
    PlaybackSection,
    PlaybackSectionSpec,
    TickPlaybackWorkerSpec,
    TimeDilationPolicy,
    playback_section_for_tick_cycle,
)
from user_devices.opx.tick_segment_compile import (
    emit_segment_tick_qua,
    qua_wait_scaled_cycles,
)

CYCLES_PER_SECOND = int(1e9 / 4)
"""OPX clock cycles per second of nominal Labscript time (250 MHz grid)."""

# QUA documents `wait()` as accepting up to 2^31 - 1 cycles, but long OPX1 waits
# close to that limit can execute incorrectly. Keep each emitted wait below a
# conservative 28-bit range and split longer inter-tick waits into several
# smaller `wait()` calls. The factor-of-four headroom leaves room to fold short
# remainders into the final chunk inside :func:`qua_wait_chunked`.
QUA_WAIT_MAX_CYCLES = (1 << (28 - 2)) - 1
"""Maximum cycles per individual ``qua.wait()`` emitted by this module."""

CLOCK_ELEMENT = "clock"
"""Default QUA element for section padding waits after inline tick playback."""


def qua_wait_chunked(cycles: int, element: str) -> None:
    """Emit a compile-time ``qua.wait(cycles, element)``, chunking if needed."""
    if cycles <= 0:
        return
    if cycles <= QUA_WAIT_MAX_CYCLES:
        qua.wait(cycles, element)
        return

    chunk = QUA_WAIT_MAX_CYCLES
    num_chunks = cycles // chunk
    remainder = cycles - num_chunks * chunk

    if num_chunks == 1:
        qua.wait(chunk + remainder, element)
        return

    counter = qua.declare(int)
    with qua.for_(counter, 0, counter < num_chunks - 1, counter + 1):
        qua.wait(chunk, element)
    qua.wait(chunk + remainder, element)


@contextmanager
def qua_section(
    opx: OPX,
    name: str,
    t: float,
    duration_s: float,
    *,
    playback: OPXInlineTickPlayback | Sequence[OPXInlineTickPlayback] | None = None,
    pre_align: list[str] | None = None,
    post_align: list[str] | None = None,
    time_dilation: float = 1.0,
    time_dilation_policy: TimeDilationPolicy | None = None,
    qua_var_time_dilation: QuaVariable[float] | None = None,
    qua_stream_time_dilation: QuaVariableInputStream[float] | None = None,
):
    """Register one playback section and optionally replay its ticks in QUA.

    The section is recorded in Labscript-time metadata. When ``playback`` helpers
    are supplied, each helper emits compact QUA ``wait``/``play`` loops for its
    clock line.
    """
    if not opx._tick_playbacks:
        raise LabscriptError("Call enable_tick_playback() before using qua_section().")

    resolved_policy = time_dilation_policy or TimeDilationPolicy.fixed
    if playback is None:
        playbacks: list[OPXInlineTickPlayback] = []
    elif isinstance(playback, OPXInlineTickPlayback):
        playbacks = [playback]
    else:
        playbacks = list(playback)

    opx._playback_sections.append(
        PlaybackSection(
            name=name,
            start=t,
            stop=(t + duration_s),
            time_dilation=time_dilation,
            time_dilation_policy=resolved_policy,
        )
    )

    if pre_align:
        qua.align(CLOCK_ELEMENT, *pre_align)

    if playbacks:
        match resolved_policy:
            case TimeDilationPolicy.input_stream:
                if qua_var_time_dilation is None or qua_stream_time_dilation is None:
                    raise RuntimeError(
                        "Input-stream tick playback requires `qua_var_time_dilation` "
                        "and `qua_stream_time_dilation` on `qua_section()`."
                    )
                qua.receive_from_stream(qua_stream_time_dilation)
                qua.assign(qua_var_time_dilation, qua_stream_time_dilation)
                for playback_helper in playbacks:
                    playback_helper.qua_play_section(name, qua_var_time_dilation)
            case TimeDilationPolicy.qua_logic:
                if qua_var_time_dilation is None:
                    raise RuntimeError(
                        "QUA-logic tick playback requires `qua_var_time_dilation` "
                        "on `qua_section()`."
                    )
                for playback_helper in playbacks:
                    playback_helper.qua_play_section(name, qua_var_time_dilation)
            case TimeDilationPolicy.fixed:
                for playback_helper in playbacks:
                    playback_helper.qua_play_section(name, time_dilation)

    try:
        yield
    finally:
        if resolved_policy != TimeDilationPolicy.qua_logic:
            seconds = duration_s * time_dilation
            qua_wait_chunked(int(seconds * CYCLES_PER_SECOND), CLOCK_ELEMENT)
        if post_align:
            qua.align(CLOCK_ELEMENT, *post_align)


def _section_name_to_tick_indices(
    spec: TickPlaybackWorkerSpec,
) -> dict[str, list[int]]:
    """Map each section name to indices into ``spec.tick_cycles``."""
    indices_by_section = {section.name: [] for section in spec.sections}
    for index, tick_cycle in enumerate(spec.tick_cycles):
        section = playback_section_for_tick_cycle(int(tick_cycle), spec.sections)
        indices_by_section.setdefault(section.name, []).append(index)
    return indices_by_section


def _qua_wait_for_tick(
    index: int,
    time_dilation: QuaVariable[float],
    spec: TickPlaybackWorkerSpec,
    playback_section: PlaybackSectionSpec,
) -> None:
    """Emit the scaled inter-tick wait before one pseudoclock tick pulse."""
    elapsed_pulse_cycles = 0 if index == 0 else spec.tick_pulse_cycles
    if playback_section.time_dilation_policy == TimeDilationPolicy.input_stream:
        wait_cycles = qua.declare(int)
        qua_wait_scaled_cycles(
            int(spec.delta_cycles[index]),
            time_dilation,
            spec.tick_element,
            wait_cycles,
            subtract_cycles=elapsed_pulse_cycles,
        )
    else:
        interval_cycles = round(
            int(spec.delta_cycles[index]) * playback_section.time_dilation
        )
        wait_cycles_i = max(interval_cycles - elapsed_pulse_cycles, 0)
        qua_wait_chunked(wait_cycles_i, spec.tick_element)


def _ensure_unique_nonempty(values: list[tuple[str, str]], label: str) -> None:
    """Raise if any named QUA resource is reused by multiple playback lines."""
    seen: dict[str, str] = {}
    for clock_line_name, value in values:
        if not value:
            continue
        previous_line = seen.get(value)
        if previous_line is not None:
            raise RuntimeError(
                f"OPX tick-only playback requires unique {label}; "
                f"{value!r} is used by both {previous_line!r} and "
                f"{clock_line_name!r}."
            )
        seen[value] = clock_line_name


def _validate_tick_only_specs(specs: Sequence[TickPlaybackWorkerSpec]) -> None:
    """Validate cross-line constraints for one generated tick-only QUA program."""
    for spec in specs:
        if not spec.sections:
            raise RuntimeError(
                f"OPX tick playback line {spec.clock_line_name!r} requires at least "
                "one registered playback section."
            )
        if any(
            section.time_dilation_policy == TimeDilationPolicy.qua_logic
            for section in spec.sections
        ):
            raise RuntimeError(
                "OPX tick playback section time_dilation_policy 'qua_logic' requires "
                "inline tick playback with a stored experiment QUA program. "
                "The tick-only fallback only handles 'fixed' and 'input_stream' "
                "policies."
            )
    _ensure_unique_nonempty(
        [(spec.clock_line_name, spec.tick_element) for spec in specs],
        "tick elements",
    )
    _ensure_unique_nonempty(
        [
            (spec.clock_line_name, spec.time_dilation_input_stream)
            for spec in specs
            if _uses_input_stream(spec)
        ],
        "time-dilation input streams",
    )
    _ensure_unique_nonempty(
        [
            (spec.clock_line_name, str(spec.timestamp_stream_name))
            for spec in specs
            if spec.timestamp_stream_name is not None
        ],
        "timestamp stream names",
    )
    _ensure_unique_nonempty(
        [
            (
                spec.clock_line_name,
                str(spec.value_stream_name or f"{spec.timestamp_stream_name}_values"),
            )
            for spec in specs
            if spec.timestamp_stream_name is not None
        ],
        "tick value stream names",
    )


def _uses_input_stream(spec: TickPlaybackWorkerSpec) -> bool:
    """Return true if any section in one line receives dilation at runtime."""
    return any(
        section.time_dilation_policy == TimeDilationPolicy.input_stream
        for section in spec.sections
    )


def _emit_tick_only_line(
    spec: TickPlaybackWorkerSpec,
    *,
    tick_timestamp_stream: ResultStreamSource | None,
    tick_value_stream: ResultStreamSource | None,
) -> None:
    """Emit tick-only QUA for one independent pseudoclock line."""
    ordered_sections = sorted(
        spec.sections,
        key=lambda section: (section.start_cycles, section.name),
    )
    section_tick_plans = spec.section_tick_plans
    indices_by_section = _section_name_to_tick_indices(spec)

    time_dilation = qua.declare(qua.fixed)
    time_dilation_stream = (
        qua.declare_input_stream(qua.fixed, spec.time_dilation_input_stream)
        if _uses_input_stream(spec)
        else None
    )

    qua.assign(time_dilation, spec.default_time_dilation)

    for section in ordered_sections:
        if section.time_dilation_policy == TimeDilationPolicy.input_stream:
            if time_dilation_stream is None:
                raise RuntimeError(
                    f"Input-stream playback line {spec.clock_line_name!r} did "
                    "not declare a time-dilation input stream."
                )
            qua.receive_from_stream(time_dilation_stream)
            qua.assign(time_dilation, time_dilation_stream)
            active_time_dilation: QuaVariable[float] | float = time_dilation
        else:
            qua.assign(time_dilation, section.time_dilation)
            active_time_dilation = section.time_dilation

        if section_tick_plans:
            emit_segment_tick_qua(
                section_tick_plans.get(section.name, []),
                tick_element=spec.tick_element,
                tick_operation=spec.tick_operation,
                tick_pulse_cycles=spec.tick_pulse_cycles,
                time_dilation=active_time_dilation,
                tick_timestamp_stream=tick_timestamp_stream,
                tick_value_stream=tick_value_stream,
            )
            continue

        for tick_index in indices_by_section.get(section.name, []):
            _qua_wait_for_tick(tick_index, time_dilation, spec, section)

            if tick_timestamp_stream is not None and tick_value_stream is not None:
                qua.play(
                    spec.tick_operation,
                    spec.tick_element,
                    timestamp_stream=tick_timestamp_stream,
                )
                qua.save(1, tick_value_stream)
            else:
                qua.play(spec.tick_operation, spec.tick_element)


def build_tick_only_fallback_program(
    specs: Sequence[TickPlaybackWorkerSpec],
) -> Program:
    """Build a tick-only QUA program from one or more playback line specs."""
    playback_specs = list(specs)
    if not playback_specs:
        raise RuntimeError("OPX tick playback requires at least one playback spec.")
    _validate_tick_only_specs(playback_specs)

    with qua.program() as program:
        tick_streams: dict[str, tuple[ResultStreamSource, ResultStreamSource]] = {}
        for playback_spec in playback_specs:
            if playback_spec.timestamp_stream_name is not None:
                tick_streams[playback_spec.clock_line_name] = (
                    qua.declare_output_stream(),
                    qua.declare_output_stream(),
                )

        qua.align()

        for playback_spec in playback_specs:
            streams = tick_streams.get(playback_spec.clock_line_name)
            tick_timestamp_stream = streams[0] if streams is not None else None
            tick_value_stream = streams[1] if streams is not None else None
            _emit_tick_only_line(
                playback_spec,
                tick_timestamp_stream=tick_timestamp_stream,
                tick_value_stream=tick_value_stream,
            )

        if tick_streams:
            with qua.stream_processing():
                for playback_spec in playback_specs:
                    streams = tick_streams.get(playback_spec.clock_line_name)
                    if streams is None:
                        continue
                    tick_timestamp_stream, tick_value_stream = streams
                    value_stream_name = playback_spec.value_stream_name or (
                        f"{playback_spec.timestamp_stream_name}_values"
                    )
                    tick_timestamp_stream.save_all(
                        str(playback_spec.timestamp_stream_name)
                    )
                    tick_value_stream.save_all(str(value_stream_name))

    return program
