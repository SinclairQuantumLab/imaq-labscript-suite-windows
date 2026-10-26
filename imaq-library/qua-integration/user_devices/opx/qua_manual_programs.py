"""Generic, config-derived QUA program for BLACS manual-mode control.

Builds one infinite-loop QUA program covering every declared
`OPXManualChannel` (see `labscript_devices.py`) at once. Each channel
becomes one independently gated QM element: a runtime-mutable operation,
frequency, amplitude, phase, and duration, all driven by QUA input streams so
a knob change from BLACS (`OPXWorker.program_manual`) never needs a recompile.

Input streams only update when the QUA program calls `advance_input_stream`,
and that call blocks until the client pushes a new value (see QM's "Input
streams" docs). So every knob is advanced on every loop iteration, and
`OPXWorker` runs a background thread (`_manual_program_push_loop`) that
continuously re-pushes the last-set value for every knob at
`MANUAL_PROGRAM_PUSH_INTERVAL_S` -- this is what keeps the loop advancing,
not a one-off push per change. A channel's `duration` knob doubles as "how
long between re-checks for a new command": set it comfortably above the push
interval (see `DEFAULT_DURATION_CYCLES`) for gap-free output, since the OPX
just pauses (not glitches) if the next push is late.

Apparatus code that needs different manual behaviour should not modify this
module: override `OPXWorker.build_manual_qua_program(...)` instead.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from qm import Program, qua
from qm.type_hinting.config_types import FullQuaConfig

if TYPE_CHECKING:
    from labscript_utils.connections import ConnectionTable

MANUAL_CHANNEL_DEVICE_CLASS = "OPXManualChannel"

ACTIVE_KNOB = "active"
OPERATION_KNOB = "operation"
FREQUENCY_KNOB = "frequency"
AMPLITUDE_KNOB = "amplitude"
PHASE_KNOB = "phase"
DURATION_KNOB = "duration"

KNOBS = (
    ACTIVE_KNOB,
    OPERATION_KNOB,
    FREQUENCY_KNOB,
    AMPLITUDE_KNOB,
    PHASE_KNOB,
    DURATION_KNOB,
)

MANUAL_PROGRAM_PUSH_INTERVAL_S = 0.1
"""How often `OPXWorker`'s background thread re-pushes every knob's value."""

_CYCLES_PER_SECOND = 250_000_000  # 1 QUA clock cycle = 4 ns.

DEFAULT_DURATION_CYCLES = int(2.5 * MANUAL_PROGRAM_PUSH_INTERVAL_S * _CYCLES_PER_SECOND)
"""Default `duration` knob value: 2.5x the push interval, for headroom."""

KNOB_DEFAULTS: dict[str, object] = {
    ACTIVE_KNOB: False,
    OPERATION_KNOB: 0,
    AMPLITUDE_KNOB: 0.0,
    PHASE_KNOB: 0.0,
    DURATION_KNOB: DEFAULT_DURATION_CYCLES,
}
"""Value pushed for a knob before any front-panel value has been recorded.

`frequency` is omitted here: use `default_knob_value()` so it can fall back to
the QM element's `intermediate_frequency` from the config.
"""

KNOB_AO_PROPERTIES: dict[str, dict[str, object]] = {
    FREQUENCY_KNOB: {
        "base_unit": "Hz",
        "min": -400e6,
        "max": 400e6,
        "step": 1e3,
        "decimals": 0,
    },
    AMPLITUDE_KNOB: {
        "base_unit": "arb",
        "min": -2.0,
        "max": 2.0,
        "step": 1e-3,
        "decimals": 4,
    },
    PHASE_KNOB: {
        "base_unit": "turns",
        "min": -1.0,
        "max": 1.0,
        "step": 1e-3,
        "decimals": 4,
    },
    DURATION_KNOB: {
        "base_unit": "cycles",
        "min": 4,
        "max": 1_000_000_000,
        "step": 1,
        "decimals": 0,
    },
}
"""BLACS `create_analog_outputs` properties for the numeric front-panel knobs.

`amplitude` is a QUA `amp()` scale factor (dimensionless, roughly `[-2, 2)`),
not a physical voltage; `phase` is in turns/cycles, matching `frame_rotation`
directly; `duration` is in QUA clock cycles, matching `play(duration=...)`
directly. Used by `blacs_tabs.py`.
"""


@dataclass(frozen=True)
class ManualChannelSpec:
    """One manually controllable QM element (mirrors `OPXManualChannel`)."""

    name: str
    element: str
    operations: tuple[str, ...]
    kind: str = "single_input"


def input_stream_name(channel_name: str, knob: str) -> str:
    """Return the QUA input-stream name `OPXWorker.program_manual` pushes to.

    Front-panel widgets must use this same naming to address a channel's knobs.
    """
    if knob not in KNOBS:
        raise ValueError(
            f"Unknown manual channel knob {knob!r}; expected one of {KNOBS!r}."
        )
    return f"{channel_name}__{knob}"


def element_intermediate_frequency_hz(
    config: FullQuaConfig, element_name: str
) -> int | None:
    """Return one element's `intermediate_frequency` in Hz, or `None` if unset."""
    element = (config.get("elements") or {}).get(element_name)
    if element is None:
        return None
    if_freq = element.get("intermediate_frequency")
    if if_freq is None:
        return None
    return int(if_freq)


def default_knob_value(
    knob: str,
    *,
    config: FullQuaConfig | None = None,
    element: str | None = None,
) -> object:
    """Return the value to push for `knob` before the front panel has set one."""
    if knob == FREQUENCY_KNOB:
        if config is not None and element is not None:
            if_freq = element_intermediate_frequency_hz(config, element)
            if if_freq is not None:
                return if_freq
        return 0
    if knob not in KNOB_DEFAULTS:
        raise ValueError(
            f"Unknown manual channel knob {knob!r}; expected one of {KNOBS!r}."
        )
    return KNOB_DEFAULTS[knob]


def _validate_channels(
    config: FullQuaConfig, channels: Sequence[ManualChannelSpec]
) -> None:
    if not channels:
        return
    elements = config.get("elements") or {}
    seen_names: set[str] = set()
    for channel in channels:
        if channel.name in seen_names:
            raise ValueError(f"Duplicate manual channel name {channel.name!r}.")
        seen_names.add(channel.name)
        if not channel.operations:
            raise ValueError(
                f"Manual channel {channel.name!r} has no operations to switch over."
            )
        element_config = elements.get(channel.element)
        if element_config is None:
            raise ValueError(
                f"Manual channel {channel.name!r} references unknown QM element "
                f"{channel.element!r}."
            )
        available_ops = element_config.get("operations") or {}
        missing = [op for op in channel.operations if op not in available_ops]
        if missing:
            raise ValueError(
                f"Manual channel {channel.name!r} declares operations {missing!r} "
                f"not present on QM element {channel.element!r} "
                f"(available: {sorted(available_ops)!r})."
            )


def _emit_channel(channel: ManualChannelSpec) -> None:
    """Emit one gated, input-stream-driven infinite loop for a manual channel.

    Every knob is advanced every iteration: `advance_input_stream` blocks
    until a new value has been pushed, so this loop can only iterate as fast
    as `OPXWorker`'s background push thread supplies fresh values for *all*
    six streams (module docstring). Advancing them unconditionally, before
    the active/inactive branch, keeps a stalled push from ever being
    possible for a subset of a channel's knobs.
    """
    active = qua.declare_input_stream(
        bool, input_stream_name(channel.name, ACTIVE_KNOB)
    )
    operation_index = qua.declare_input_stream(
        int, input_stream_name(channel.name, OPERATION_KNOB)
    )
    frequency = qua.declare_input_stream(
        int, input_stream_name(channel.name, FREQUENCY_KNOB)
    )
    amplitude = qua.declare_input_stream(
        qua.fixed, input_stream_name(channel.name, AMPLITUDE_KNOB)
    )
    phase = qua.declare_input_stream(
        qua.fixed, input_stream_name(channel.name, PHASE_KNOB)
    )
    duration = qua.declare_input_stream(
        int, input_stream_name(channel.name, DURATION_KNOB)
    )

    with qua.infinite_loop_():
        qua.advance_input_stream(active)
        qua.advance_input_stream(operation_index)
        qua.advance_input_stream(frequency)
        qua.advance_input_stream(amplitude)
        qua.advance_input_stream(phase)
        qua.advance_input_stream(duration)
        with qua.if_(active):
            qua.update_frequency(channel.element, frequency)
            # `frame_rotation` is cumulative; reset first so the phase knob
            # sets an absolute angle each iteration, not an ever-growing drift.
            qua.reset_frame(channel.element)
            qua.frame_rotation(phase, channel.element)
            with qua.switch_(operation_index):
                for index, operation_name in enumerate(channel.operations):
                    with qua.case_(index):
                        qua.play(
                            operation_name * qua.amp(amplitude),
                            channel.element,
                            duration=duration,
                        )


def build_manual_program(
    config: FullQuaConfig, channels: Sequence[ManualChannelSpec]
) -> Program:
    """Build one infinite-loop QUA program covering every manual channel.

    Every knob is backed by a QUA input stream named
    `input_stream_name(channel.name, <knob>)`. The program never needs
    recompiling for a knob change: only `push_to_input_stream` calls are
    needed (see `OPXWorker.program_manual`).
    """
    _validate_channels(config, channels)

    with qua.program() as manual_program:
        for channel in channels:
            _emit_channel(channel)

    return manual_program


def manual_channel_specs_from_connection_table(
    connection_table: ConnectionTable, device_name: str
) -> list[ManualChannelSpec]:
    """Discover an OPX's `OPXManualChannel` children from the BLACS connection table.

    Used by `OPXTab.initialise_workers()` to pass manual channel specs to the
    worker before any shot has compiled (the connection table is loaded at
    BLACS startup), and reused by the front panel to build widgets.
    """
    specs: list[ManualChannelSpec] = []
    for connection in connection_table.table.values():
        if (
            connection.parent_name == device_name
            and connection.device_class == MANUAL_CHANNEL_DEVICE_CLASS
        ):
            properties = connection.properties
            specs.append(
                ManualChannelSpec(
                    name=connection.name,  # ty: ignore[invalid-argument-type]
                    element=properties["element"],
                    operations=tuple(properties["operations"]),
                    kind=properties["kind"],
                )
            )
    return specs
