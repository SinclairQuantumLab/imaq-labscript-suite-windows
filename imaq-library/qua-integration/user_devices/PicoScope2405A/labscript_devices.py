import json

from labscript import TriggerableDevice, LabscriptError


class PicoScope2405A(TriggerableDevice):
    description = "PicoScope 2405A oscilloscope"

    def __init__(
        self,
        name,
        parent_device,
        connection,
        BLACS_connection="",
        default_trigger_channel="D",
        default_trigger_threshold_V=1.0,
        default_voltage_range="5V",
        default_coupling="DC",
        **kwargs,
    ):
        TriggerableDevice.__init__(
            self,
            name,
            parent_device,
            connection,
            **kwargs,
        )

        self.BLACS_connection = BLACS_connection
        self.default_trigger_channel = default_trigger_channel
        self.default_trigger_threshold_V = default_trigger_threshold_V
        self.default_voltage_range = default_voltage_range
        self.default_coupling = default_coupling

        self.captures = []

    def capture(
        self,
        t,
        name="trace",
        channels=("A",),
        trigger_channel=None,
        trigger_threshold_V=None,
        sample_rate_Hz=5e6,
        pre_trigger_s=0.0,
        post_trigger_s=1e-3,
        voltage_range=None,
        coupling=None,
        trigger_direction="rising",
        trigger_duration=1e-3,
        acquisition_timeout_s=10.0,
    ):
        if len(self.captures) > 0:
            raise LabscriptError(
                "This first PicoScope2405A implementation only supports "
                "one capture per shot."
            )

        if trigger_channel is None:
            trigger_channel = self.default_trigger_channel

        if trigger_threshold_V is None:
            trigger_threshold_V = self.default_trigger_threshold_V

        if voltage_range is None:
            voltage_range = self.default_voltage_range

        if coupling is None:
            coupling = self.default_coupling

        channels = self._normalise_channels(channels)
        trigger_channel = self._normalise_channel(trigger_channel)

        if trigger_channel not in ("A", "B", "C", "D"):
            raise LabscriptError(
                f"Invalid PicoScope trigger_channel {trigger_channel!r}. "
                "Use 'A', 'B', 'C', or 'D'."
            )

        if len(channels) == 0:
            raise LabscriptError("PicoScope capture must save at least one channel.")

        if sample_rate_Hz <= 0:
            raise LabscriptError("sample_rate_Hz must be positive.")

        if pre_trigger_s < 0:
            raise LabscriptError("pre_trigger_s must be >= 0.")

        if post_trigger_s <= 0:
            raise LabscriptError("post_trigger_s must be > 0.")

        if trigger_duration <= 0:
            raise LabscriptError("trigger_duration must be > 0.")

        if acquisition_timeout_s <= 0:
            raise LabscriptError("acquisition_timeout_s must be > 0.")

        voltage_range = self._normalise_voltage_range(voltage_range)
        coupling = str(coupling).upper()
        trigger_direction = str(trigger_direction).lower()

        if coupling not in ("AC", "DC"):
            raise LabscriptError("PicoScope coupling must be 'AC' or 'DC'.")

        if trigger_direction not in ("rising", "falling", "above", "below"):
            raise LabscriptError(
                "trigger_direction must be 'rising', 'falling', 'above', or 'below'."
            )

        # This schedules the actual labscript TTL trigger pulse through the
        # parent Trigger object.
        self.trigger(t, trigger_duration)

        self.captures.append(
            {
                "name": str(name),
                "t": float(t),
                "channels": list(channels),
                "trigger_channel": trigger_channel,
                "trigger_threshold_V": float(trigger_threshold_V),
                "sample_rate_Hz": float(sample_rate_Hz),
                "pre_trigger_s": float(pre_trigger_s),
                "post_trigger_s": float(post_trigger_s),
                "voltage_range": voltage_range,
                "coupling": coupling,
                "trigger_direction": trigger_direction,
                "trigger_duration": float(trigger_duration),
                "acquisition_timeout_s": float(acquisition_timeout_s),
            }
        )

    def generate_code(self, hdf5_file):
        TriggerableDevice.generate_code(self, hdf5_file)

        group = self.init_device_group(hdf5_file)

        group.attrs["BLACS_connection"] = self.BLACS_connection
        group.attrs["default_trigger_channel"] = self.default_trigger_channel
        group.attrs["default_trigger_threshold_V"] = self.default_trigger_threshold_V
        group.attrs["default_voltage_range"] = self.default_voltage_range
        group.attrs["default_coupling"] = self.default_coupling

        # This is the main thing the BLACS worker will read in
        # transition_to_buffered().
        group.attrs["captures_json"] = json.dumps(self.captures)

    def _normalise_channels(self, channels):
        if isinstance(channels, str):
            if "," in channels:
                channels = [ch.strip() for ch in channels.split(",")]
            else:
                channels = list(channels)

        return tuple(self._normalise_channel(ch) for ch in channels)

    def _normalise_channel(self, channel):
        channel = str(channel).strip().upper()

        if channel.startswith("CHANNEL_"):
            channel = channel.replace("CHANNEL_", "")

        if channel.startswith("CH"):
            channel = channel.replace("CH", "")

        if channel not in ("A", "B", "C", "D"):
            raise LabscriptError(
                f"Invalid PicoScope channel {channel!r}. "
                "Use 'A', 'B', 'C', or 'D'."
            )

        return channel

    def _normalise_voltage_range(self, voltage_range):
        voltage_range = str(voltage_range).strip().upper()
        voltage_range = voltage_range.replace(" ", "")
        voltage_range = voltage_range.replace("PS2000A_", "")
        voltage_range = voltage_range.replace("MILLIVOLT", "MV")
        voltage_range = voltage_range.replace("MVOLT", "MV")
        voltage_range = voltage_range.replace("VOLT", "V")

        allowed_ranges = {
            "10MV",
            "20MV",
            "50MV",
            "100MV",
            "200MV",
            "500MV",
            "1V",
            "2V",
            "5V",
            "10V",
            "20V",
            "50V",
        }

        if voltage_range not in allowed_ranges:
            raise LabscriptError(
                f"Invalid PicoScope voltage_range {voltage_range!r}. "
                f"Allowed values are: {sorted(allowed_ranges)}"
            )

        return voltage_range