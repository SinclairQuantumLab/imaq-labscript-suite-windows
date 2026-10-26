from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, TypedDict, cast

import numpy as np

if TYPE_CHECKING:
    import h5py
from labscript import (
    AnalogOut,
    ClockLine,
    Device,
    DigitalOut,
    LabscriptError,
    Pseudoclock,
    PseudoclockDevice,
)
from labscript.compiler import compiler
from labscript.outputs import Output
from qm import Program, QuantumMachinesManager, qua
from qm.qua._dsl.stream_processing.stream_processing import ResultStreamSource
from qm.qua._expressions import QuaVariable
from qm.type_hinting.config_types import FullQuaConfig
from user_devices.opx.config_serialization import (
    DATASET_ATTR_SERIALIZATION,
    qm_config_to_json_bytes,
)
from user_devices.opx.execution_mode import (
    EXECUTION_MODE_EXECUTE,
    ExecutionMode,
    normalize_execution_mode,
    uses_precompiled_program_id,
)
from user_devices.opx.qua_program_print import print_qua_program
from user_devices.opx.result_io import (
    ResultWriteMetadata,
    write_result_metadata_attrs,
)
from user_devices.opx.shot_stream_metadata import (
    InputStreamValues,
    compute_program_fingerprint,
    normalize_input_stream_values,
    write_execution_mode,
    write_input_stream_values,
)
from user_devices.opx.tick_playback_types import (
    InlineTickCommand,
    PlaybackControlMode,
    PlaybackSection,
    TickPlaybackConfig,
    normalise_playback_sections,
)
from user_devices.opx.tick_segment_compile import (
    build_section_tick_plans,
    emit_segment_tick_qua,
    emit_segment_tick_qua_precomputed_step,
    write_tick_segments_hdf5,
)


class OutputStateSnapshot(TypedDict):
    """Snapshot of mutable labscript output state restored after QUA rebuilds."""

    instructions: dict[object, object]
    ramp_limits: list[object]


OPX_CLOCK_CYCLE_S = 4e-9

DEFAULT_MAX_INLINE_SECTIONS = 64


def _validate_input_stream_values(
    values: InputStreamValues | None, *, description: str
) -> InputStreamValues:
    """Validate and normalize per-shot QUA input-stream values at compile time."""
    try:
        return normalize_input_stream_values(values, description=description)
    except (ValueError, TypeError) as exc:
        raise LabscriptError(str(exc)) from exc


def _qm_config_has_hardware(config: object) -> bool:
    """Return whether a QM config has controllers or elements worth storing."""
    if not isinstance(config, dict):
        return False
    return bool(config.get("controllers") or config.get("elements"))


class OPXPseudoclock(Pseudoclock):
    """The internal Labscript pseudoclock owned by an `OPX` device.

    Labscript pseudoclock devices expose a pseudoclock and clockline to their
    child devices. This OPX implementation may expose several independent
    clocklines, each replayed by a separate QUA tick element.
    """

    def add_device(self, device: Device) -> None:
        """Allow child `ClockLine` instances and reject all other devices."""
        if isinstance(device, ClockLine):
            Pseudoclock.add_device(self, device)
        else:
            raise LabscriptError(
                f"You have connected {device.name} to {self.name} (the Pseudoclock of {self.parent_device.name}), "
                f"but {self.name} only supports children that are ClockLines. "
                f"Please connect your device to one of {self.parent_device.name}.clock_lines instead."
            )

    def expand_change_times(
        self,
        all_change_times: Sequence[float],
        change_times: dict[ClockLine, list[float]],
        outputs_by_clockline: dict[ClockLine, list[Output]],
    ) -> tuple[dict[ClockLine, list[np.ndarray | float]], list[object]]:
        """Expand each OPX clock line independently.

        Labscript's base pseudoclock compiler uses one maximum ramp rate across
        all clock lines that change at the same time. For OPX playback we need
        independent physical tick trains, so each Labscript `ClockLine` is
        expanded against only its own outputs and clock limit.
        """
        del all_change_times  # Line-local expansion intentionally ignores this.

        all_times: dict[ClockLine, list[np.ndarray | float]] = {
            clock_line: [] for clock_line in outputs_by_clockline
        }
        clock: list[object] = []
        emitted_wait_times: set[float] = set()

        for clock_line, clock_line_change_times in change_times.items():
            outputs = outputs_by_clockline[clock_line]
            local_clock_limit = min(self.clock_limit, clock_line.clock_limit)

            for index, time in enumerate(clock_line_change_times):
                if (
                    time in self.parent_device.trigger_times[1:]
                    and time not in emitted_wait_times
                ):
                    clock.append("WAIT")
                    emitted_wait_times.add(time)

                maxrate = 0.0
                for output in outputs:
                    if not hasattr(output, "timeseries"):
                        continue
                    output_instruction = output.timeseries[index]
                    if not isinstance(output_instruction, dict):
                        continue
                    maxrate = max(maxrate, float(output_instruction["clock rate"]))

                if maxrate:
                    period = 1 / maxrate
                    quantised_period = round(period / self.clock_resolution)
                    period = quantised_period * self.clock_resolution
                    maxrate = 1 / period
                if maxrate > local_clock_limit:
                    raise LabscriptError(
                        f"At t = {time} sec, a clock rate of {maxrate} Hz was "
                        f"requested on ClockLine {clock_line.name}. One or more "
                        "connected devices on that line cannot support clock rates "
                        f"higher than {local_clock_limit} Hz."
                    )

                try:
                    next_time = clock_line_change_times[index + 1]
                except IndexError:
                    if self.parent_device.stop_time > time:
                        raise LabscriptError(
                            f"ClockLine {clock_line.name} has its last change time "
                            f"at t={time:.15f}, before the experiment stop time "
                            f"t={self.parent_device.stop_time:.15f}. This should "
                            "have been filled in by collect_change_times()."
                        )
                    if self.parent_device.stop_time < time:
                        raise LabscriptError(
                            f"ClockLine {clock_line.name} has instructions at "
                            f"t={time:.15f} after the experiment stop time "
                            f"t={self.parent_device.stop_time:.15f}. Extend the "
                            "section duration or call stop() later."
                        )
                    all_times[clock_line].append(time)
                    clock.append(
                        {
                            "start": time,
                            "reps": 1,
                            "step": 10.0 / local_clock_limit,
                            "enabled_clocks": [clock_line],
                        }
                    )
                    continue

                if maxrate:
                    n_ticks_float = (next_time - time) * maxrate
                    n_ticks, remainder = np.divmod(n_ticks_float, 1)
                    n_ticks = int(n_ticks)
                    if (
                        remainder
                        and remainder / float(maxrate) >= 1 / local_clock_limit
                    ):
                        n_ticks += 1
                    if n_ticks <= 0:
                        all_times[clock_line].append(time)
                        clock.append(
                            {
                                "start": time,
                                "reps": 1,
                                "step": next_time - time,
                                "enabled_clocks": [clock_line],
                            }
                        )
                        continue

                    duration = n_ticks / float(maxrate)
                    ticks = np.linspace(time, time + duration, n_ticks, endpoint=False)
                    all_times[clock_line].append(ticks)

                    if n_ticks > 1:
                        clock.append(
                            {
                                "start": time,
                                "reps": n_ticks - 1,
                                "step": 1 / float(maxrate),
                                "enabled_clocks": [clock_line],
                            }
                        )
                    clock.append(
                        {
                            "start": float(ticks[-1]),
                            "reps": 1,
                            "step": next_time - float(ticks[-1]),
                            "enabled_clocks": [clock_line],
                        }
                    )
                else:
                    all_times[clock_line].append(time)
                    clock.append(
                        {
                            "start": time,
                            "reps": 1,
                            "step": next_time - time,
                            "enabled_clocks": [clock_line],
                        }
                    )

        clock.sort(key=lambda entry: entry["start"] if isinstance(entry, dict) else -1)
        return all_times, clock


class OPXResultTrace(AnalogOut):
    """Placeholder channel for OPX/QM result data saved after a shot.

    This is not a Labscript-driven analog output. It gives Runviewer and Lyse a
    stable channel name under which the BLACS worker can store result handles
    fetched from the completed QUA job.
    """

    description = "OPX result trace"

    def __init__(
        self,
        name: str,
        parent_device: PseudoclockDevice,
        connection: str,
        **kwargs: object,
    ) -> None:
        """Create a result placeholder with a harmless analog default value."""
        kwargs.setdefault("default_value", 0.0)
        AnalogOut.__init__(self, name, parent_device, connection, **kwargs)


class OPXManualChannel(Device):
    """Inert labscript child declaring one BLACS-manual-mode-controllable QM element.

    Carries the metadata BLACS needs to build a front-panel widget group and
    know which QUA input streams to push knob changes into (see
    `qua_manual_programs.py` and `blacs_tabs.py`). It has no Labscript
    instructions of its own -- it contributes nothing to `generate_code()`
    output (the inherited `Device.generate_code()` just recurses into its own,
    empty, `child_devices`) and is never added to a `ClockLine`, so it is
    invisible to `OPXPseudoclock.expand_change_times`.
    """

    description = "OPX manual channel"
    allowed_children = ()

    KIND_SINGLE_INPUT = "single_input"
    KIND_IQ = "iq"
    _VALID_KINDS = (KIND_SINGLE_INPUT, KIND_IQ)

    def __init__(
        self,
        name: str,
        parent_device: OPX,
        element: str,
        operations: Sequence[str],
        kind: str = KIND_SINGLE_INPUT,
        **kwargs: object,
    ) -> None:
        """Declare one manually controllable QM element.

        Parameters
        ----------
        element:
            QM config element name this channel controls. Also used as the
            Labscript `connection` string.
        operations:
            Names of QM operations available on `element` (as they appear
            under that element's `operations` mapping in the QM config).
            The generic manual QUA program switches between these at runtime;
            the front panel populates its operation dropdown from this list.
        kind:
            `"single_input"` or `"iq"`. Determines whether the front panel
            exposes one amplitude/phase pair or per-tone IQ controls.
        """
        if kind not in self._VALID_KINDS:
            raise LabscriptError(
                f"OPXManualChannel {name!r} has kind={kind!r}; expected one of "
                f"{self._VALID_KINDS!r}."
            )
        operations = tuple(operations)
        if not operations:
            raise LabscriptError(
                f"OPXManualChannel {name!r} needs at least one operation name."
            )

        Device.__init__(
            self, name, parent_device=parent_device, connection=element, **kwargs
        )
        self.element = element
        self.operations = operations
        self.kind = kind

        # Persisted as connection-table properties (not device_properties), so
        # BLACS can enumerate manual channels and build front-panel widgets
        # straight from the connection table, before any shot has compiled --
        # the same reasoning as OPX's own connection settings.
        self.set_property("element", element, location="connection_table_properties")
        self.set_property(
            "operations", list(operations), location="connection_table_properties"
        )
        self.set_property("kind", kind, location="connection_table_properties")


class OPXInlineTickPlayback:
    """Emit inline QUA tick replay from compact Labscript clock segments.

    Returned by :meth:`OPX.enable_inline_tick_playback`. Register a QUA program
    builder via :meth:`OPX.set_qua_program_builder`; :meth:`OPX.generate_code`
    compiles ``pseudoclock.clock`` into per-section segment plans and then builds
    the final QUA program so each :meth:`qua_play_section` call emits parametric
    ``wait``/``play`` loops instead of iterating a flattened tick table.
    """

    def __init__(
        self,
        opx: OPX,
        clock_line: ClockLine,
        tick_element: str,
        tick_operation: str,
        tick_pulse_cycles: int,
        timestamp_stream_name: str | None,
        value_stream_name: str | None,
        max_inline_sections: int = DEFAULT_MAX_INLINE_SECTIONS,
    ) -> None:
        self.opx = opx
        self.clock_line = clock_line
        self.clock_line_name = clock_line.name
        self.tick_element = tick_element
        self.tick_operation = tick_operation
        self.tick_pulse_cycles = tick_pulse_cycles
        self.timestamp_stream_name = timestamp_stream_name
        self.value_stream_name = value_stream_name
        self._max_inline_sections = max_inline_sections
        self.opx._max_inline_sections_by_line[self.clock_line_name] = (
            max_inline_sections
        )
        self._ps_tick_timestamp_stream: ResultStreamSource | None = None
        self._ps_tick_value_stream: ResultStreamSource | None = None

    def _ensure_tick_streams(self) -> None:
        if self.timestamp_stream_name is None:
            return
        if self._ps_tick_timestamp_stream is None or self._ps_tick_value_stream is None:
            raise RuntimeError(
                "Tick result streams are not initialised. Call "
                "`playback.qua_prepare_tick_playback()` at the start of the QUA "
                "program before `qua_play_section()` or `save_tick_trace()`."
            )

    def qua_prepare_tick_playback(self) -> None:
        """Declare tick timestamp/value streams at the start of each QUA program.

        The QUA program builder may run twice (script registration, then compile
        with segment ticks). Streams must be declared inside the active
        ``qua.program()`` context and must not be reused across builds.
        """
        if self.timestamp_stream_name is None:
            return
        self._ps_tick_timestamp_stream = qua.declare_output_stream()
        self._ps_tick_value_stream = qua.declare_output_stream()

    def reset_tick_streams(self) -> None:
        """Forget QUA stream objects from a previous ``qua.program()`` build."""
        self._ps_tick_timestamp_stream = None
        self._ps_tick_value_stream = None

    def _segments_for_section(self, section_name: str):
        """Register a play-section call and return its compiled segments, if ready."""
        command = self.opx._register_inline_tick_command(
            clock_line_name=self.clock_line_name,
            section_name=section_name,
        )
        if command.index >= self._max_inline_sections:
            raise RuntimeError(
                f"OPX inline tick playback command index {command.index} exceeds "
                f"max_inline_sections={self._max_inline_sections}."
            )
        if not self.opx._emit_segment_tick_qua:
            return None
        if self.opx._section_tick_plans is None:
            raise RuntimeError(
                "OPX section tick plans are not available yet. When inline tick "
                "playback is enabled, register the QUA program with "
                "`opx.set_qua_program_builder(...)` so `generate_code()` can "
                "compile pseudoclock segments before building the program."
            )
        self._ensure_tick_streams()
        return self.opx._section_tick_plans.get(self.clock_line_name, {}).get(
            section_name, []
        )

    def qua_play_section(
        self,
        section_name: str,
        time_dilation: QuaVariable | float,
    ) -> None:
        """Emit QUA code to play one section's compiled tick segments."""
        segments = self._segments_for_section(section_name)
        if segments is None:
            return
        emit_segment_tick_qua(
            segments,
            tick_element=self.tick_element,
            tick_operation=self.tick_operation,
            tick_pulse_cycles=self.tick_pulse_cycles,
            time_dilation=time_dilation,
            tick_timestamp_stream=self._ps_tick_timestamp_stream,
            tick_value_stream=self._ps_tick_value_stream,
        )

    def qua_play_section_precomputed_step(
        self,
        section_name: str,
        *,
        base_step_cycles: int,
        scaled_step_cycles: QuaVariable[int],
        scaled_step_minus_pulse_cycles: QuaVariable[int],
    ) -> None:
        """Emit one section using precomputed runtime integer wait variables.

        This preserves QUA ``wait(variable, ...)`` while avoiding
        ``Cast.mul_int_by_fixed`` in dense tick loops. Use it for runtime choices
        from a discrete set of known dilations.
        """
        segments = self._segments_for_section(section_name)
        if segments is None:
            return
        emit_segment_tick_qua_precomputed_step(
            segments,
            tick_element=self.tick_element,
            tick_operation=self.tick_operation,
            tick_pulse_cycles=self.tick_pulse_cycles,
            base_step_cycles=base_step_cycles,
            scaled_step_cycles=scaled_step_cycles,
            scaled_step_minus_pulse_cycles=scaled_step_minus_pulse_cycles,
            tick_timestamp_stream=self._ps_tick_timestamp_stream,
            tick_value_stream=self._ps_tick_value_stream,
        )

    def save_tick_trace(self) -> None:
        """Save emitted tick timestamps inside the user's stream-processing block."""
        tick_timestamp_stream = self._ps_tick_timestamp_stream
        tick_value_stream = self._ps_tick_value_stream
        if tick_timestamp_stream is None or tick_value_stream is None:
            return
        tick_timestamp_stream.save_all(str(self.timestamp_stream_name))
        tick_value_stream.save_all(str(self.value_stream_name))


class OPX(PseudoclockDevice):
    """Labscript device for Quantum Machines OPX hardware.

    One class supports two deployment roles:

    - **Master pseudoclock** (no ``trigger_device``): replay Labscript ticks from
      QUA, run inline measurements, export results. Typical modes: ``execute`` or
      ``precompiled_program_id``.
    - **Triggered OPX** (``trigger_device`` set): QUA waits for external TTL via
      ``wait_for_trigger(...)``. Typical modes: ``precompiled_program_id`` or
      ``execute``.

    **Compile time** — experiment scripts call:

    - :meth:`set_qm_config` — QM hardware config dict
    - :meth:`set_qua_program` / :meth:`set_qua_program_builder` — experiment QUA program
    - :meth:`enable_inline_tick_playback` / :meth:`enable_tick_playback` — tick replay (master role)
    - :func:`~user_devices.opx.qua_tick_programs.qua_section` — section boundaries with tick playback
    - :meth:`add_result_trace` — post-shot export instructions

    :meth:`generate_code` writes everything under ``devices/<name>/`` in the shot
    HDF5 file.

    **Runtime** — :class:`~user_devices.opx.blacs_workers.OPXWorker`
    loads the HDF5 payload, executes on the OPX for the selected
    ``execution_mode``, pushes input-stream values, and exports ``RESULTS/``.
    """

    description = "OPX"
    allowed_children = (OPXPseudoclock, OPXManualChannel)

    def __init__(
        self,
        name: str,
        host: str,
        cluster_name: str,
        port: int | str | None = None,
        trigger_device: Device | None = None,
        trigger_connection: str | None = None,
        blacs_connection: str = "opx_blacs_connection",
        debug_qua_programs: bool = False,
        **kwargs: object,
    ) -> None:
        """Create an OPX device and its internal Labscript clock line.

        Parameters
        ----------
        name:
            Labscript device name.
        host, cluster_name, port:
            Quantum Machines connection settings persisted into each compiled shot.
        trigger_device, trigger_connection:
            When set, the OPX is a **triggered segment runner** (secondary in
            Labscript). Omit for a **master pseudoclock** deployment.
        blacs_connection:
            BLACS connection label used by Labscript device registration.
        debug_qua_programs:
            If true, print generated QUA programs during compile-time debugging.
        **kwargs:
            Additional keyword arguments forwarded to `PseudoclockDevice`.
        """
        self.name = name
        self.host = host
        if isinstance(port, str):
            port = int(port)
        self.port = port
        self.clock_limit = 1e9  # 1 GHz
        self.clock_resolution = 4e-9  # 250 MHz timing grid
        self.cluster_name = cluster_name
        self.debug_qua_programs = debug_qua_programs

        # Labscript device classes initialise via their concrete base class.
        PseudoclockDevice.__init__(
            self,
            name,
            trigger_device=trigger_device,
            trigger_connection=trigger_connection,
            **kwargs,
        )

        # Connection settings and role are constructor arguments, fixed for the
        # whole apparatus (every experiment script imports the same connection
        # table and constructs this device the same way). Persisting them as
        # connection-table properties (rather than only device_properties in
        # each shot) makes them available to the BLACS worker via
        # `create_worker()`'s automatic property merge, before any shot has
        # run. This is what lets manual mode open a QM connection manager at
        # BLACS startup. Do not put `qm_config` here: it legitimately varies
        # per experiment script, and BLACS rejects any shot whose connection
        # table properties differ from the one it loaded at startup.
        self.set_property("qm_host", host, location="connection_table_properties")
        self.set_property(
            "qm_cluster_name",
            cluster_name,
            location="connection_table_properties",
        )
        self.set_property("qm_port", self.port, location="connection_table_properties")
        self.set_property(
            "is_master_pseudoclock",
            self.is_master_pseudoclock,
            location="connection_table_properties",
        )

        self.BLACS_connection = blacs_connection
        self.qm_config: FullQuaConfig = FullQuaConfig()
        self.qua_program: Program | None = None
        self._result_traces: list[ResultWriteMetadata] = []
        self._tick_playbacks: dict[str, TickPlaybackConfig] = {}
        self._inline_tick_playbacks: dict[str, OPXInlineTickPlayback] = {}
        self._playback_sections: list[PlaybackSection] = []
        self._inline_tick_commands: dict[str, list[InlineTickCommand]] = {}
        self._max_inline_sections_by_line: dict[str, int] = {}
        self._qua_program_builder: Callable[[], Program] | None = None
        self._section_tick_plans: dict[str, dict[str, list]] | None = None
        self._emit_segment_tick_qua: bool = True
        self._execution_mode: ExecutionMode = EXECUTION_MODE_EXECUTE
        self._input_stream_values: InputStreamValues = {}
        # Keep the historical attribute without opening a network connection during
        # connection-table import. BLACS constructs the live manager at run time.
        self.qmm: QuantumMachinesManager | None = None

        self.pseudoclock = OPXPseudoclock(
            name=f"{name}_pseudoclock",
            pseudoclock_device=self,
            connection="pseudoclock",
        )

        self.clock_line = ClockLine(
            name=f"{name}_clock_line",
            pseudoclock=self.pseudoclock,
            connection="internal",
        )

    @property
    def clock_lines(self) -> list[ClockLine]:
        """Return all clock lines owned by this OPX pseudoclock."""
        return [
            device
            for device in self.pseudoclock.child_devices
            if isinstance(device, ClockLine)
        ]

    def add_clock_line(self, name: str, connection: str) -> ClockLine:
        """Create an additional independent Labscript clock line on this OPX."""
        if any(clock_line.name == name for clock_line in self.clock_lines):
            raise LabscriptError(
                f"OPX device {self.name} already has clock line {name!r}."
            )
        return ClockLine(
            name=name,
            pseudoclock=self.pseudoclock,
            connection=connection,
        )

    def _clock_line_by_name(self, clock_line_name: str) -> ClockLine:
        """Return a managed clock line by its HDF5/storage name."""
        for clock_line in self.clock_lines:
            if clock_line.name == clock_line_name:
                return clock_line
        raise LabscriptError(
            f"OPX device {self.name} has no clock line named {clock_line_name!r}."
        )

    def _resolve_clock_line(self, clock_line: ClockLine | None = None) -> ClockLine:
        """Resolve a user-supplied clock-line reference to a managed `ClockLine`."""
        if clock_line is None:
            return self.clock_line
        if clock_line not in self.clock_lines:
            raise LabscriptError(
                f"Clock line {clock_line.name!r} is not owned by OPX device {self.name}."
            )
        return clock_line

    def _reset_inline_tick_streams(self) -> None:
        """Forget QUA stream objects for every inline playback helper."""
        for playback in self._inline_tick_playbacks.values():
            playback.reset_tick_streams()

    def enable_tick_playback(
        self,
        tick_element: str,
        tick_operation: str,
        tick_pulse_cycles: int = 4,
        default_time_dilation: float = 1.0,
        control_mode: PlaybackControlMode = PlaybackControlMode.section_table,
        time_dilation_input_stream: str = "opx_tick_time_dilation",
        auto_push_input_stream_defaults: bool = True,
        timestamp_stream_name: str | None = None,
        value_stream_name: str | None = None,
        clock_line: ClockLine | None = None,
    ) -> None:
        """Enable QUA playback of Labscript's compiled pseudoclock ticks.

        Parameters
        ----------
        tick_element, tick_operation:
            QUA element and operation used to emit the physical pseudoclock tick.
        tick_pulse_cycles:
            Duration of the emitted tick pulse in OPX clock cycles (4 ns each).
            Inter-tick waits are computed from tick-start to tick-start, so this
            pulse width is subtracted from each interval after scaling.
        default_time_dilation:
            Nominal wall-clock time multiplier. Values above 1 play slower;
            values below 1 play faster.
        control_mode:
            ``"section_table"`` uses section time dilations stored in the shot file.
            ``"input_stream"`` lets the QUA program receive a ``fixed`` time
            multiplier at the start of each input-stream-controlled section.
        time_dilation_input_stream:
            Name of the QUA client input stream for runtime time-dilation updates.
        auto_push_input_stream_defaults:
            If true, the worker pushes section default time dilations immediately after
            starting the job so shots run unattended. Set false when an external
            controller should intentionally block/resume playback section by
            section.
        timestamp_stream_name:
            Optional QUA stream-processing handle for tick timestamps.
        value_stream_name:
            Optional QUA stream-processing handle for one value per emitted tick.
            If omitted while `timestamp_stream_name` is set, a default name is
            derived by appending ``"_values"`` to the timestamp stream name.
        clock_line:
            Optional clock line for this playback channel. Omit for the default
            `opx.clock_line`.
        """
        resolved_clock_line = self._resolve_clock_line(clock_line)
        clock_line_name = resolved_clock_line.name
        config = TickPlaybackConfig(
            clock_line_name=clock_line_name,
            tick_element=tick_element,
            tick_operation=tick_operation,
            tick_pulse_cycles=tick_pulse_cycles,
            default_time_dilation=default_time_dilation,
            control_mode=control_mode,
            time_dilation_input_stream=time_dilation_input_stream,
            auto_push_input_stream_defaults=auto_push_input_stream_defaults,
            timestamp_stream_name=timestamp_stream_name,
            value_stream_name=value_stream_name,
        )
        self._tick_playbacks[clock_line_name] = config

    def enable_inline_tick_playback(
        self,
        tick_element: str,
        tick_operation: str,
        tick_pulse_cycles: int = 4,
        default_time_dilation: float = 1.0,
        control_mode: PlaybackControlMode = PlaybackControlMode.section_table,
        time_dilation_input_stream: str = "opx_tick_time_dilation",
        auto_push_input_stream_defaults: bool = True,
        timestamp_stream_name: str | None = None,
        value_stream_name: str | None = None,
        max_inline_sections: int = DEFAULT_MAX_INLINE_SECTIONS,
        clock_line: ClockLine | None = None,
    ) -> OPXInlineTickPlayback:
        """Enable inline segment-based tick playback inside the experiment QUA program.

        Pair the returned helper with :meth:`set_qua_program_builder` and
        :func:`~user_devices.opx.qua_tick_programs.qua_section`.
        :meth:`generate_code` compiles ``pseudoclock.clock`` into compact tick
        segments and then builds the final QUA program.
        """
        self.enable_tick_playback(
            tick_element=tick_element,
            tick_operation=tick_operation,
            tick_pulse_cycles=tick_pulse_cycles,
            clock_line=clock_line,
            default_time_dilation=default_time_dilation,
            control_mode=control_mode,
            time_dilation_input_stream=time_dilation_input_stream,
            auto_push_input_stream_defaults=auto_push_input_stream_defaults,
            timestamp_stream_name=timestamp_stream_name,
            value_stream_name=value_stream_name,
        )
        resolved_clock_line = self._resolve_clock_line(clock_line)
        clock_line_name = resolved_clock_line.name
        config = self._tick_playbacks[clock_line_name].model_copy(
            update={"inline_playback": True, "inline_max_sections": max_inline_sections}
        )
        self._tick_playbacks[clock_line_name] = config
        self._inline_tick_commands[clock_line_name] = []
        self._max_inline_sections_by_line[clock_line_name] = max_inline_sections
        playback = OPXInlineTickPlayback(
            opx=self,
            clock_line=resolved_clock_line,
            tick_element=tick_element,
            tick_operation=tick_operation,
            tick_pulse_cycles=tick_pulse_cycles,
            timestamp_stream_name=timestamp_stream_name,
            value_stream_name=config.value_stream_name,
            max_inline_sections=max_inline_sections,
        )
        self._inline_tick_playbacks[clock_line_name] = playback
        return playback

    def set_qua_program_builder(self, builder: Callable[[], Program]) -> None:
        """Register a callable that builds the experiment QUA program.

        With inline tick playback, the builder runs twice: once immediately to
        record Labscript outputs and playback sections, then again from
        :meth:`generate_code` after tick segments are compiled from
        ``pseudoclock.clock``.

        Without inline tick playback, the builder runs once at registration and
        the returned program is stored on :attr:`qua_program` (including when the
        builder interleaves compile-time Labscript instructions for triggered
        secondary shots).
        """
        self._qua_program_builder = builder
        self._emit_segment_tick_qua = False
        self._section_tick_plans = {}
        self._playback_sections.clear()
        for clock_line_name in list(self._inline_tick_commands):
            self._inline_tick_commands[clock_line_name] = []
        self._reset_inline_tick_streams()
        has_inline_playback = any(
            tick_playback.inline_playback
            for tick_playback in self._tick_playbacks.values()
        )
        if has_inline_playback:
            builder()
        else:
            self.qua_program = builder()

    def set_execution_mode(self, mode: ExecutionMode | str) -> None:
        """Select how BLACS starts OPX jobs for this device.

        ``execute`` (default) compiles and runs the stored QUA program on every
        shot via ``qm.execute(program)``.

        ``precompiled_program_id`` compiles the QUA program once on the cluster,
        caches the returned ``program_id`` for the duration of the BLACS session,
        and starts each shot with ``add_compiled(program_id)``. Per-shot scalar
        updates must be supplied through :meth:`set_input_stream_values`.
        """
        self._execution_mode = normalize_execution_mode(str(mode))

    def set_input_stream_values(
        self,
        values: InputStreamValues,
    ) -> None:
        """Register per-shot QUA input-stream values for BLACS to push at runtime.

        These values are written into each compiled shot HDF5 file. They are
        intended for ``precompiled_program_id`` mode, where the QUA program
        structure stays fixed and only stream payloads change shot to shot.
        """
        self._input_stream_values = _validate_input_stream_values(
            values, description="OPX input-stream"
        )

    def clear_input_stream_values(self) -> None:
        """Forget any per-shot input-stream values registered on this device."""
        self._input_stream_values = {}

    def _build_qua_program_with_segment_ticks(self, stop_time: float) -> Program:
        """Build the final QUA program with segment-based tick playback."""
        if self._qua_program_builder is None:
            raise LabscriptError(
                f"OPX device {self.name} inline tick playback requires "
                "`opx.set_qua_program_builder(...)`."
            )
        if not self._tick_playbacks:
            raise LabscriptError(
                f"OPX device {self.name} does not have tick playback enabled."
            )

        section_tick_plans: dict[str, dict[str, list]] = {}
        for clock_line_name, tick_playback in self._tick_playbacks.items():
            if not tick_playback.inline_playback:
                continue
            clock_line = self._clock_line_by_name(clock_line_name)
            section_tick_plans[clock_line_name] = build_section_tick_plans(
                self.pseudoclock.clock,
                clock_line,
                list(self._playback_sections),
                stop_time,
                list(self._inline_tick_commands.get(clock_line_name, [])),
                default_time_dilation=tick_playback.default_time_dilation,
                control_mode=tick_playback.control_mode,
                clock_cycle_s=OPX_CLOCK_CYCLE_S,
            )
        self._section_tick_plans = section_tick_plans

        self._emit_segment_tick_qua = True
        self._playback_sections.clear()
        for clock_line_name in list(self._inline_tick_commands):
            self._inline_tick_commands[clock_line_name] = []
        self._reset_inline_tick_streams()
        return self._run_qua_program_builder_preserving_labscript_outputs()

    def _iter_clockline_outputs(self):
        """Yield every labscript :class:`Output` attached to OPX clock lines."""
        for clock_line in self.clock_lines:
            for intermediate_device in clock_line.child_devices:
                for channel in intermediate_device.child_devices:
                    yield from channel.get_all_outputs()

    def _snapshot_output_state(self) -> dict[Output, OutputStateSnapshot]:
        """Capture compile-time output instructions before a QUA-only rebuild."""
        return {
            output: {
                "instructions": dict(output.instructions),
                "ramp_limits": list(output.ramp_limits),
            }
            for output in self._iter_clockline_outputs()
        }

    def _restore_output_state(
        self, snapshots: dict[Output, OutputStateSnapshot]
    ) -> None:
        """Restore compile-time output instructions after a QUA-only rebuild."""
        for output, state in snapshots.items():
            output.instructions = dict(state["instructions"])
            output.ramp_limits = list(state["ramp_limits"])

    def _run_qua_program_builder_preserving_labscript_outputs(self) -> Program:
        """Run the QUA builder without duplicating labscript output instructions.

        Inline tick playback compiles the builder twice: once at script time to
        register labscript outputs and playback sections, and again at
        ``generate_code()`` to emit segment-based tick QUA. Replay Labscript
        calls into temporary output tables, then restore the compiled state.
        """
        maybe_builder = self._qua_program_builder
        if maybe_builder is None:
            raise LabscriptError(
                f"OPX device {self.name} does not have a QUA program builder."
            )
        saved_outputs = self._snapshot_output_state()
        previous_suppress = compiler.suppress_all_warnings
        try:
            # Compiled ramp limits have already been quantised to the clock grid.
            # Re-adding nominal ramps against those limits can falsely overlap
            # (for example, 0.825 versus 0.8250000000000001 seconds).
            for output in saved_outputs:
                output.instructions = {}
                output.ramp_limits = []
            compiler.suppress_all_warnings = True
            builder = cast(Callable[[], Program], maybe_builder)  # ty: ignore[redundant-cast]
            return builder()
        finally:
            compiler.suppress_all_warnings = previous_suppress
            self._restore_output_state(saved_outputs)

    def _register_inline_tick_command(
        self,
        clock_line_name: str,
        section_name: str,
    ) -> InlineTickCommand:
        """Record one inline QUA tick-playback command for validation and HDF5.

        Each command corresponds to one `OPXInlineTickPlayback.qua_play_section()`
        call. `generate_code()` writes the command order into HDF5 for debugging.
        """
        commands = self._inline_tick_commands.setdefault(clock_line_name, [])
        command = InlineTickCommand(
            index=len(commands),
            clock_line_name=clock_line_name,
            section_name=section_name,
        )
        commands.append(command)
        return command

    def add_result_trace(
        self,
        handle: str,
        trace_name: str,
        sample_period: float,
        t0: float = 0.0,
        timestamp_scale: float = 1.0,
        timestamp_handle: str | None = None,
        align_to_first_timestamp: bool = False,
        clock_line: ClockLine | None = None,
    ) -> None:
        """Register one named QUA result for later export into the shot file.

        This method is called at compile time from the experiment script. It
        does not fetch any data yet. Instead it records how BLACS should export
        a future QM result handle after the shot has finished.

        Parameters
        ----------
        handle:
            Name of the QM result handle to fetch from `job.result_handles`.
            This should match the name used by QUA stream processing, for
            example `save_all("tag")`.
        trace_name:
            Stable labscript-side name for the saved result. In practice this
            will usually match an `OPXResultTrace` channel name from the
            connection table so Runviewer and Lyse can find the data under that
            channel.
        sample_period:
            Sample spacing in seconds for uniformly sampled data. Use a positive
            value for regularly sampled traces such as raw ADC streams. Use
            `0.0` when the result should instead be timed by explicit QM
            timestamps.
        t0:
            Shot-time offset in seconds applied when reconstructing the trace.
            For uniformly sampled data this is the time of the first sample. For
            timestamped data it is the reference time added after any timestamp
            scaling and optional alignment.
        timestamp_scale:
            Conversion factor in seconds per raw QM timestamp unit. This is not
            a universal OPX constant; it depends on what kind of timestamps that
            particular result handle returns.

            Typical cases in this codebase are:

            - raw ADC traces saved with `.with_timestamps()`: the embedded
              timestamps are typically in nanoseconds, so use `1e-9`,
            - separate measurement timestamp streams saved via
              `timestamp_stream=...`: the timestamps are typically in OPX clock
              cycles, so use `4e-9`.

            If a result is reconstructed only from `sample_period` and does not
            use timestamps at all, this value is effectively ignored.
        timestamp_handle:
            Optional second QM result handle containing timestamps for `handle`.
            Use this when values and timestamps are returned as separate result
            streams, such as a scalar measurement stream plus a separate
            `timestamp_stream`. Leave this as `None` when timestamps are already
            embedded in the value payload, for example with
            `.with_timestamps().save_all(...)`.
        align_to_first_timestamp:
            If `True`, treat `t0` as the known shot time of the first returned
            timestamp and shift the whole trace so that its first finite
            timestamp lands at `t0`. This is mainly useful for externally
            triggered secondary OPX jobs that may have been armed before
            labscript shot time `t = 0`.

        Notes
        -----
        The metadata stored here is later written by `generate_code()` into the
        device HDF5 group. The BLACS worker then uses it to fetch the requested
        handle(s), store the raw payload in the shot file, and expose the result
        under `trace_name` for Runviewer and Lyse.

        We validate names and handles here because collisions would otherwise
        only show up much later when BLACS tries to save results.
        """
        for trace in self._result_traces:
            if trace["trace_name"] == trace_name:
                raise LabscriptError(
                    f"Duplicate OPX result trace name '{trace_name}' for device {self.name}."
                )
            used_handles = {trace["handle"]}
            existing_timestamp_handle = trace.get("timestamp_handle")
            if existing_timestamp_handle is not None:
                used_handles.add(existing_timestamp_handle)
            if handle in used_handles:
                raise LabscriptError(
                    f"Duplicate OPX result handle '{handle}' for device {self.name}."
                )
            if timestamp_handle is not None and timestamp_handle in used_handles:
                raise LabscriptError(
                    f"Duplicate OPX timestamp handle '{timestamp_handle}' for device "
                    f"{self.name}."
                )

        clock_line_name = (
            self._resolve_clock_line(clock_line).name
            if clock_line is not None
            else None
        )
        self._result_traces.append(
            {
                # Store only simple serialisable metadata. The actual samples will
                # be produced by the running OPX job and fetched by the worker.
                "handle": handle,
                "trace_name": trace_name,
                "clock_line_name": clock_line_name,
                "sample_period": sample_period,
                "t0": t0,
                "timestamp_scale": timestamp_scale,
                # Secondary externally triggered OPX jobs are often armed before
                # the master shot starts, so QM timestamps can be relative to the
                # arming time rather than labscript shot time. When this flag is
                # set, readers reinterpret `t0` as the shot-time anchor for the
                # first returned timestamp and shift the whole trace accordingly.
                "align_to_first_timestamp": align_to_first_timestamp,
                "timestamp_handle": timestamp_handle,
            }
        )

    def _write_digital_traces(self, group: h5py.Group) -> float:
        """Persist labscript digital output instructions into the device HDF5 group.

        In labscript, child `DigitalOut` devices already have their per-clock-tick
        values compiled into `raw_output`, and the pseudoclock has already computed
        the absolute tick times for the clockline. This helper converts that
        in-memory compile result into datasets that the worker and runviewer can
        read later.

        The structure written here is:

        - `DIGITAL_TRACES/<channel>/times`: the pseudoclock tick times in seconds
        - `DIGITAL_TRACES/<channel>/values`: the compiled 0/1 state at each tick

        The returned stop time is used as a simple device-level shot duration.
        """
        traces_group = group.create_group("DIGITAL_TRACES")
        stop_time = 0.0

        for clock_line in self.clock_lines:
            # `times[clock_line]` is populated by the base labscript compiler. It
            # is the canonical time axis for outputs attached to this line.
            times = np.asarray(
                self.pseudoclock.times.get(clock_line, []),
                dtype=np.float64,
            )
            if len(times):
                stop_time = max(stop_time, float(times[-1]))

            for intermediate_device in clock_line.child_devices:
                for channel in intermediate_device.child_devices:
                    if not isinstance(channel, DigitalOut):
                        continue

                    channel_group = traces_group.create_group(channel.name)
                    channel_group.attrs["clock_line_name"] = clock_line.name
                    channel_group.create_dataset("times", data=times)
                    channel_group.create_dataset(
                        "values",
                        # `raw_output` is the already-compiled digital state sequence
                        # aligned to the pseudoclock times above.
                        data=np.asarray(channel.raw_output, dtype=np.uint8),
                    )

        return stop_time

    def _seconds_to_cycles(
        self, values_s: Sequence[float] | np.ndarray, label: str
    ) -> np.ndarray:
        """Convert second-valued times to integer OPX cycles on the 4 ns grid.

        Raises `LabscriptError` if any input time cannot be represented on the
        OPX timing grid. This catches invalid section boundaries and compiled
        tick times during compilation instead of letting BLACS fail at runtime.
        """
        values_s = np.asarray(values_s, dtype=np.float64)
        cycles = np.rint(values_s / OPX_CLOCK_CYCLE_S).astype(np.int64)
        reconstructed = cycles.astype(np.float64) * OPX_CLOCK_CYCLE_S
        if not np.allclose(values_s, reconstructed, rtol=0.0, atol=1e-12):
            raise LabscriptError(
                f"OPX {label} contains times that are not on the 4 ns QUA grid."
            )
        return cycles

    def _write_tick_playback(self, group: h5py.Group, stop_time: float) -> None:
        """Persist compiled pseudoclock tick playback metadata into HDF5."""
        if not self._tick_playbacks:
            return
        playback_group = group.create_group("TICK_PLAYBACK")
        playback_group.attrs["schema_version"] = 2
        playback_group.attrs["clock_cycle_s"] = OPX_CLOCK_CYCLE_S
        clock_lines_group = playback_group.create_group("CLOCK_LINES")

        for clock_line_name, tick_playback in self._tick_playbacks.items():
            clock_line = self._clock_line_by_name(clock_line_name)
            times = np.asarray(
                self.pseudoclock.times.get(clock_line, []),
                dtype=np.float64,
            )
            tick_cycles = self._seconds_to_cycles(
                times,
                f"pseudoclock tick table for {clock_line_name}",
            )
            if len(tick_cycles) and np.any(np.diff(tick_cycles) < 0):
                raise LabscriptError(
                    f"OPX pseudoclock tick table for {clock_line_name} is not monotonic."
                )

            commands = self._inline_tick_commands.get(clock_line_name, [])
            command_count = len(commands)
            max_sections = self._max_inline_sections_by_line.get(
                clock_line_name,
                DEFAULT_MAX_INLINE_SECTIONS,
            )
            if command_count > max_sections:
                raise LabscriptError(
                    f"OPX inline tick playback on {clock_line_name} has {command_count} "
                    "`qua_play_section` calls, but max_inline_sections="
                    f"{max_sections}. Increase `max_inline_sections` in "
                    "`enable_inline_tick_playback()`."
                )

            line_group = clock_lines_group.create_group(clock_line_name)
            line_group.create_dataset("tick_cycles", data=tick_cycles)
            line_group.create_dataset(
                "delta_cycles",
                data=np.diff(np.concatenate(([0], tick_cycles))).astype(np.int64),
            )

            for key, value in tick_playback.model_dump(mode="json").items():
                if value is not None:
                    line_group.attrs[key] = value
            sections_group = line_group.create_group("SECTIONS")
            for index, section in enumerate(
                normalise_playback_sections(
                    self._playback_sections,
                    stop_time,
                    default_time_dilation=tick_playback.default_time_dilation,
                    control_mode=tick_playback.control_mode,
                    clock_resolution=self.clock_resolution,
                )
            ):
                section_group = sections_group.create_group(f"{index:04d}")
                section_group.attrs["name"] = section.name
                section_group.attrs["start"] = section.start
                section_group.attrs["stop"] = section.stop
                section_group.attrs["start_cycles"] = int(
                    self._seconds_to_cycles([section.start], "playback section start")[
                        0
                    ]
                )
                section_group.attrs["stop_cycles"] = int(
                    self._seconds_to_cycles([section.stop], "playback section stop")[0]
                )
                section_group.attrs["time_dilation"] = section.time_dilation
                section_group.attrs["time_dilation_policy"] = (
                    section.time_dilation_policy.value
                )

            if commands:
                commands_group = line_group.create_group("INLINE_COMMANDS")
                for command in commands:
                    command_group = commands_group.create_group(f"{command.index:04d}")
                    command_group.attrs["index"] = command.index
                    command_group.attrs["clock_line_name"] = command.clock_line_name
                    command_group.attrs["section_name"] = command.section_name
                if self._section_tick_plans is not None:
                    write_tick_segments_hdf5(
                        line_group,
                        self._section_tick_plans.get(clock_line_name, {}),
                        commands,
                    )

    # --- minimal generate_code: write just what the Worker needs ---
    def generate_code(self, hdf5_file: h5py.File) -> None:
        """Translate the compiled labscript device state into shot-file contents.

        This is the main handoff point between the labscript compiler and the
        runtime worker:

        - During compilation, the experiment script configures this `OPX` object
          with a QM config, a compiled QUA program, digital output instructions,
          and optional result-trace metadata.
        - `generate_code()` serialises that state into the HDF5 shot file under
          `devices/<device_name>/...`.
        - Later, the BLACS worker opens the same HDF5 group, reconstructs the QM
          config and protobuf-encoded QUA program, executes the job, and writes
          the acquired results back into the shot file.

        For labscript users this method often feels mysterious because it runs at
        compile time, not at shot runtime. Nothing here talks to the OPX hardware
        directly; it only prepares the shot description that the worker will use.
        """
        # Let the base labscript machinery finish compiling common pseudoclock
        # state first. This populates timing structures such as
        # `self.pseudoclock.times[clock_line]` for every OPX clock line.
        PseudoclockDevice.generate_code(self, hdf5_file)
        grp = self.init_device_group(hdf5_file)

        # Save the digital outputs that labscript scheduled on this device.
        stop_time = self._write_digital_traces(grp)

        has_inline_playback = any(
            tick_playback.inline_playback
            for tick_playback in self._tick_playbacks.values()
        )
        if has_inline_playback:
            self.qua_program = self._build_qua_program_with_segment_ticks(stop_time)
        elif self._qua_program_builder is not None and self.qua_program is None:
            self.qua_program = self._qua_program_builder()

        self._write_tick_playback(grp, stop_time)
        self.set_property(
            "is_master_pseudoclock",
            self.is_master_pseudoclock,
            location="device_properties",
        )
        # `stop_time` lets downstream code know the nominal end of this device's
        # activity in shot time.
        self.set_property("stop_time", stop_time, location="device_properties")

        # The worker needs the same QM connection settings that were defined in
        # the connection table. Persist them into the shot so BLACS does not have
        # its own separate source of truth.
        grp.attrs["qm_host"] = self.host
        grp.attrs["qm_cluster_name"] = self.cluster_name
        grp.attrs["is_master_pseudoclock"] = self.is_master_pseudoclock
        if self.port is not None:
            grp.attrs["qm_port"] = self.port

        write_execution_mode(grp, self._execution_mode)
        write_input_stream_values(grp, self._input_stream_values)

        config = self.qm_config
        # We are compiling offline into a shot file, not querying hardware
        # capabilities from a live OPX during compilation.
        QuantumMachinesManager.set_capabilities_offline(frozenset())

        cfg_bytes = b""
        writes_qua_config = (
            self.qua_program is not None
            or bool(self._tick_playbacks)
            or _qm_config_has_hardware(self.qm_config)
        )
        if writes_qua_config:
            cfg_bytes = qm_config_to_json_bytes(config)
            arr = np.frombuffer(cfg_bytes, dtype=np.uint8)
            dataset = grp.create_dataset("qua_config", data=arr, dtype="u1")
            dataset.attrs["serialization"] = DATASET_ATTR_SERIALIZATION

        if self.qua_program is not None:
            # The QUA program itself is stored as QM's protobuf representation so
            # the worker can execute the exact compiled program without rebuilding
            # it from Python source.
            if self.debug_qua_programs:
                print_qua_program(
                    self.qua_program,
                    device_name=self.name,
                    stage="after labscript compile",
                )
            buffered_program = self.qua_program.to_protobuf(config)
            program_bytes = bytes(buffered_program)
            arr = np.frombuffer(program_bytes, dtype=np.uint8)
            grp.create_dataset("qua_program", data=arr, dtype="u1")
            if uses_precompiled_program_id(self._execution_mode):
                grp.attrs["program_fingerprint"] = compute_program_fingerprint(
                    qua_config_bytes=cfg_bytes,
                    qua_program_bytes=program_bytes,
                )

        if self._result_traces:
            # This metadata tells the worker which QM result handles to fetch and
            # how to map them into stable result names in the shot file.
            metadata_group = grp.create_group("RESULT_METADATA")
            for trace in self._result_traces:
                trace_group = metadata_group.create_group(trace["trace_name"])
                write_result_metadata_attrs(trace_group, trace)
