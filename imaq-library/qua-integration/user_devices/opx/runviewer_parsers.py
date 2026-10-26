import labscript_utils.h5_lock  # noqa: F401 -- must precede h5py
import h5py
import numpy as np
from user_devices.opx.result_io import (
    RESULTS_GROUP_NAME,
    build_trace_arrays,
    prepare_trace_for_runviewer,
    read_result_entry,
)


class OPXParser:
    def __init__(self, path, device):
        self.path = path
        self.name = device.name
        self.device = device

    def _iter_channels(self):
        """Yield `(channel_name, channel)` pairs from the OPX device tree.

        Runviewer gives us the connection-table device object, not the HDF5 group
        layout. For `OPX` devices the stable path is:

        `OPX -> clock_lines -> intermediate device(s) -> channel(s)`
        """
        seen = set()

        clock_lines = getattr(self.device, "clock_lines", None)
        if clock_lines:
            for clock_line in clock_lines:
                for intermediate_device in getattr(clock_line, "child_devices", []):
                    for channel in getattr(intermediate_device, "child_devices", []):
                        if channel.name in seen:
                            continue
                        seen.add(channel.name)
                        yield channel.name, channel
            return

        # Runviewer reconstructs the connection table from HDF5 into lightweight
        # `Connection` objects that expose nested `child_list` dicts.
        child_list = getattr(self.device, "child_list", None)
        if child_list is not None:
            for pseudoclock in child_list.values():
                for clock_line in getattr(pseudoclock, "child_list", {}).values():
                    for intermediate_device in getattr(
                        clock_line, "child_list", {}
                    ).values():
                        for channel in getattr(
                            intermediate_device, "child_list", {}
                        ).values():
                            if channel.name in seen:
                                continue
                            seen.add(channel.name)
                            yield channel.name, channel
            return

        # Fallback for plain nested `child_devices` lists.
        for pseudoclock in getattr(self.device, "child_devices", []):
            for clock_line in getattr(pseudoclock, "child_devices", []):
                for intermediate_device in getattr(clock_line, "child_devices", []):
                    for channel in getattr(intermediate_device, "child_devices", []):
                        if channel.name in seen:
                            continue
                        seen.add(channel.name)
                        yield channel.name, channel

    @staticmethod
    def _parent_port(channel):
        """Return the port identifier Runviewer should show for a channel."""
        return getattr(
            channel,
            "parent_port",
            getattr(channel, "connection", None),
        )

    @staticmethod
    def _compiled_analog_trace(h5_file, opx_group, channel):
        """Read fake-generator samples on their nominal Labscript clock line.

        These are compiled output plans, not measured voltages or a simulation
        of QUA time dilation. Read each line independently so auxiliary samples
        are never plotted against the primary line's update times.
        """
        parent = getattr(channel, "parent_device", None)
        if parent is None:
            parent = getattr(channel, "parent", None)
        if parent is None:
            return None
        device_class = getattr(parent, "device_class", type(parent).__name__)
        if device_class != "FakeVoltageGenerator":
            return None

        clock_line = getattr(parent, "parent_device", None)
        if clock_line is None:
            clock_line = getattr(parent, "parent", None)
        if clock_line is None:
            return None
        outputs = h5_file.get(f"devices/{parent.name}/OUTPUTS")
        ticks = opx_group.get(
            f"TICK_PLAYBACK/CLOCK_LINES/{clock_line.name}/tick_cycles"
        )
        if outputs is None or ticks is None:
            return None
        if channel.name not in (outputs.dtype.names or ()):
            return None

        values = outputs[channel.name]
        times = ticks[()].astype("float64") * 4e-9
        if len(times) != len(values):
            raise ValueError(
                f"Compiled analog channel {channel.name} has {len(values)} "
                f"samples but clock line {clock_line.name} has {len(times)} ticks."
            )
        return (times, values), parent.name

    @staticmethod
    def _compiled_clock_traces(opx_group):
        """Supply nominal clock edges so Runviewer can load child NI parsers.

        These are saved Labscript schedules, not measured OPX waveforms. Each
        clock line retains its own times, including the final duplicate sample.
        Runtime QUA dilation is intentionally not reconstructed here.
        """
        lines = opx_group.get("TICK_PLAYBACK/CLOCK_LINES")
        if lines is None:
            return {}
        clocks = {}
        for name, line in lines.items():
            ticks = np.asarray(line["tick_cycles"][()], dtype=np.float64)
            if not len(ticks):
                continue
            if np.any(np.diff(ticks) <= 0):
                raise ValueError(f"Clock line {name} has non-increasing ticks")
            widths = np.full(len(ticks), float(line.attrs["tick_pulse_cycles"]))
            if np.any(widths <= 0):
                raise ValueError(f"Clock line {name} has a non-positive pulse width")
            # This virtual clock encodes sampling instants. Keep falling edges
            # between adjacent ticks even when nominal and runtime timing differ.
            widths[:-1] = np.minimum(widths[:-1], np.diff(ticks) / 2)
            times = np.empty(2 * len(ticks))
            times[0::2] = ticks * 4e-9
            times[1::2] = (ticks + widths) * 4e-9
            values = np.zeros(2 * len(ticks), dtype=np.int8)
            values[0::2] = 1
            clocks[name] = (times, values)
        return clocks

    def get_traces(self, add_trace, clock=None):
        traces = {}
        triggers = {}

        with h5py.File(self.path, "r") as f:
            group = f.get(f"devices/{self.name}")
            if group is None:
                return triggers

            clocks = self._compiled_clock_traces(group)
            triggers.update(clocks)
            for line_name, trace in clocks.items():
                add_trace(line_name, trace, self.name, "nominal_clock_preview")

            digital_traces_group = group.get("DIGITAL_TRACES")
            results_group = group.get(RESULTS_GROUP_NAME)
            for channel_name, channel in self._iter_channels():
                analog_trace = self._compiled_analog_trace(f, group, channel)
                if analog_trace is not None:
                    trace, parent_name = analog_trace
                    traces[channel_name] = trace
                    add_trace(
                        channel_name, trace, parent_name, self._parent_port(channel)
                    )

                if (
                    digital_traces_group is not None
                    and channel_name in digital_traces_group
                ):
                    channel_group = digital_traces_group[channel_name]
                    trace = (
                        channel_group["times"][()],
                        channel_group["values"][()],
                    )
                    traces[channel_name] = trace
                    add_trace(
                        channel_name, trace, self.name, self._parent_port(channel)
                    )
                    # When a digital output channel triggers downstream devices,
                    # return child trigger node names rather than the channel name.
                    # Runviewer resolves returned names via connection_table.find_by_name()
                    # and loads each child device parser.
                    for child in getattr(channel, "child_devices", []):
                        triggers[child.name] = trace
                    for child_name in getattr(channel, "child_list", {}):
                        triggers[child_name] = trace

                if results_group is not None and channel_name in results_group:
                    result_entry = read_result_entry(group, channel_name)
                    trace_data = (
                        None
                        if result_entry is None
                        else build_trace_arrays(result_entry)
                    )
                    if trace_data is None:
                        continue
                    trace = prepare_trace_for_runviewer(
                        trace_data[0],
                        trace_data[1],
                        baseline=float(getattr(channel, "default_value", 0.0)),
                    )
                    traces[channel_name] = trace
                    add_trace(
                        channel_name, trace, self.name, self._parent_port(channel)
                    )

        return triggers
