"""
BLACS worker for a PicoScope 2405A.

This is a first-version, block-capture-only worker.

Expected use:
    - BLACS opens the PicoScope over USB using PicoSDK / ps2000a.
    - transition_to_buffered() reads capture settings from the shot HDF5 file.
    - The worker configures the PicoScope and arms it for an external trigger.
    - The labscript shot produces a TTL pulse on a PulseBlaster / NI / PrawnDO line.
    - The PicoScope sees that pulse on one of its analog input channels, usually D.
    - transition_to_manual() waits for the capture to complete, reads the waveform,
      converts ADC counts to volts, and saves the data into the shot HDF5 file.

For first testing, close PicoScope 7 before starting BLACS. PicoScope 7 and Python
usually cannot control the same scope at the same time.
"""

import ctypes
import json
import os
import time

import numpy as np

# Must be imported before h5py in labscript-suite workers.
import labscript_utils.h5_lock
import h5py

from blacs.tab_base_classes import Worker


# ---------------------------------------------------------------------------
# PicoSDK DLL discovery
# ---------------------------------------------------------------------------
# On your machine, we found ps2000a.dll in:
#     C:\Program Files\Pico Technology\PicoScope 7 T&M Stable
#
# If this folder is already in your user PATH, this block is harmless.
# If it is not in PATH, os.add_dll_directory() helps Python find ps2000a.dll.
if os.name == "nt":
    _possible_pico_dll_dirs = [
        r"C:\Program Files\Pico Technology\PicoScope 7 T&M Stable",
        r"C:\Program Files\Pico Technology\SDK\lib",
        r"C:\Program Files (x86)\Pico Technology\SDK\lib",
    ]

    for _dll_dir in _possible_pico_dll_dirs:
        if os.path.isdir(_dll_dir):
            try:
                os.add_dll_directory(_dll_dir)
            except Exception:
                pass

            # Also prepend to PATH for libraries that use normal PATH lookup.
            os.environ["PATH"] = _dll_dir + os.pathsep + os.environ.get("PATH", "")


from picosdk.ps2000a import ps2000a as ps
from picosdk.functions import adc2mV, mV2adc, assert_pico_ok


class PicoScope2405AWorker(Worker):
    """
    BLACS worker for PicoScope 2405A.

    The worker talks directly to the PicoSDK. There is no separate interface
    class in this first version.
    """

    # -----------------------------------------------------------------------
    # Worker method: init
    #
    # Called once when the BLACS worker process starts.
    #
    # This is where we open the PicoScope using PicoSDK and initialise all
    # state variables that will be reused between shots.
    #
    # Expected worker_args from blacs_tabs.py:
    #     serial_number
    #
    # serial_number should usually come from BLACS_connection in the connection
    # table. If it is "", None, or absent, PicoSDK opens the first available
    # PicoScope.
    # -----------------------------------------------------------------------
    def init(self):
        self.display_running = False
        
        self.serial_number = getattr(self, "serial_number", "")
        self.handle = ctypes.c_int16()

        if self.serial_number:
            serial = self.serial_number.encode("ascii")
            print(f"Opening PicoScope 2405A with serial {self.serial_number!r}")
        else:
            serial = None
            print("Opening first available PicoScope 2405A")

        status = ps.ps2000aOpenUnit(ctypes.byref(self.handle), serial)
        assert_pico_ok(status)

        self.max_adc = ctypes.c_int16()
        status = ps.ps2000aMaximumValue(self.handle, ctypes.byref(self.max_adc))
        assert_pico_ok(status)

        print(f"PicoScope opened successfully. Handle = {self.handle.value}")
        print(f"PicoScope max ADC value = {self.max_adc.value}")

        self.device_name = None
        self.h5_filepath = None
        self.capture = None

        self.timebase = None
        self.time_interval_ns = None
        self.pre_trigger_samples = None
        self.post_trigger_samples = None
        self.total_samples = None

        self.adc_buffers = {}
        self.channel_ranges = {}

    # -----------------------------------------------------------------------
    # Worker method: shutdown
    #
    # Called once when BLACS exits.
    #
    # This stops any active acquisition and closes the PicoScope handle cleanly.
    # -----------------------------------------------------------------------
    def shutdown(self):
        try:
            ps.ps2000aStop(self.handle)
        except Exception:
            pass

        try:
            status = ps.ps2000aCloseUnit(self.handle)
            assert_pico_ok(status)
            print("PicoScope closed.")
        except Exception as exc:
            print(f"Error while closing PicoScope: {exc}")

    # -----------------------------------------------------------------------
    # Worker method: program_manual
    #
    # Called when BLACS wants to update manual-mode front-panel values.
    #
    # For this first PicoScope version, we are not exposing any manual controls
    # in the BLACS GUI. The scope is only configured during buffered shots.
    #
    # Return value:
    #     A dictionary of coerced front-panel values. Empty is fine here.
    # -----------------------------------------------------------------------
    def program_manual(self, front_panel_values):
        return {}

    # -----------------------------------------------------------------------
    # Worker method: transition_to_buffered
    #
    # Called before the shot starts.
    #
    # This method should:
    #     1. Read the shot HDF5 file.
    #     2. Extract the PicoScope capture settings.
    #     3. Configure PicoScope channels.
    #     4. Configure the PicoScope trigger.
    #     5. Arm the PicoScope for block capture.
    #
    # Important:
    #     Do not wait for the trigger here. BLACS calls this before the shot
    #     begins. If we waited here, the shot would never get to the point where
    #     the PulseBlaster / NI / PrawnDO trigger pulse is generated.
    # -----------------------------------------------------------------------
    def transition_to_buffered(self, device_name, h5_file_path, initial_values, fresh):
        self.display_running = False
        ps.ps2000aStop(self.handle)

        self.device_name = device_name
        self.h5_filepath = h5_file_path

        self.capture = self.read_capture_settings(h5_file_path, device_name)

        if self.capture is None:
            print(f"No PicoScope capture requested for {device_name}.")
            return {}

        print("PicoScope capture settings:")
        for key, value in self.capture.items():
            print(f"    {key}: {value}")

        self.ready_acquisition()

        return {}

    # -----------------------------------------------------------------------
    # Worker method: transition_to_manual
    #
    # Called after the shot finishes.
    #
    # This method should:
    #     1. Wait for the PicoScope block capture to be ready.
    #     2. Assign data buffers.
    #     3. Read ADC samples from the PicoScope.
    #     4. Convert ADC samples to volts.
    #     5. Save the traces into the shot HDF5 file.
    #     6. Stop the PicoScope and clear shot-specific state.
    #
    # HDF5 output path:
    #     /data/traces/<device_name>/time_s
    #     /data/traces/<device_name>/A_V
    #     /data/traces/<device_name>/B_V
    #     ...
    # -----------------------------------------------------------------------
    def transition_to_manual(self):
        
        if self.capture is None:
            self.clear_shot_state()
            return True

        timeout_s = float(self.capture.get("acquisition_timeout_s", 10.0))

        self.wait_until_ready(timeout_s=timeout_s)
        traces_V = self.read_block_data()
        time_s = self.make_time_axis_s()

        with h5py.File(self.h5_filepath, "a") as hdf5_file:
            data_group = hdf5_file.require_group("data")
            trace_group = data_group.require_group(f"traces/{self.device_name}")

            if "time_s" in trace_group:
                del trace_group["time_s"]
            trace_group.create_dataset("time_s", data=time_s)

            for channel, values_V in traces_V.items():
                dataset_name = f"{channel}_V"
                if dataset_name in trace_group:
                    del trace_group[dataset_name]
                trace_group.create_dataset(dataset_name, data=values_V)

            trace_group.attrs["trigger_channel"] = self.capture["trigger_channel"]
            trace_group.attrs["sample_rate_Hz_requested"] = self.capture["sample_rate_Hz"]
            trace_group.attrs["time_interval_ns_actual"] = self.time_interval_ns
            trace_group.attrs["sample_rate_Hz_actual"] = 1e9 / self.time_interval_ns
            trace_group.attrs["pre_trigger_s"] = self.capture["pre_trigger_s"]
            trace_group.attrs["post_trigger_s"] = self.capture["post_trigger_s"]
            trace_group.attrs["pre_trigger_samples"] = self.pre_trigger_samples
            trace_group.attrs["post_trigger_samples"] = self.post_trigger_samples
            trace_group.attrs["total_samples"] = self.total_samples
            trace_group.attrs["voltage_range"] = self.capture["voltage_range"]
            trace_group.attrs["overflow"] = int(getattr(self, "last_overflow", 0))

        print(f"Saved PicoScope traces to /data/traces/{self.device_name}")

        status = ps.ps2000aStop(self.handle)
        assert_pico_ok(status)

        self.clear_shot_state()
        return True

    # -----------------------------------------------------------------------
    # Worker method: abort_transition_to_buffered
    #
    # Called if BLACS aborts after transition_to_buffered() succeeded but before
    # the shot started.
    #
    # Stop the PicoScope so it does not remain armed waiting for a trigger.
    # -----------------------------------------------------------------------
    def abort_transition_to_buffered(self):
        try:
            ps.ps2000aStop(self.handle)
        except Exception:
            pass

        self.clear_shot_state()
        return True

    # -----------------------------------------------------------------------
    # Worker method: abort_buffered
    #
    # Called if BLACS aborts during the shot.
    #
    # Stop the PicoScope and clear shot-specific state.
    # -----------------------------------------------------------------------
    def abort_buffered(self):
        try:
            ps.ps2000aStop(self.handle)
        except Exception:
            pass

        self.clear_shot_state()
        return True

    # -----------------------------------------------------------------------
    # Helper method: read_capture_settings
    #
    # Reads capture settings from the shot HDF5 file.
    #
    # Supported first-version formats:
    #
    # Format 1:
    #     /devices/<device_name>.attrs["capture_json"]
    #
    # Format 2:
    #     /devices/<device_name>/CAPTURE.attrs[...]
    #
    # This lets your labscript_devices.py be simple while we are still deciding
    # the exact final HDF5 schema.
    # -----------------------------------------------------------------------
    def read_capture_settings(self, h5_file_path, device_name):
        with h5py.File(h5_file_path, "r") as hdf5_file:
            device_group = hdf5_file["devices"][device_name]

            if "capture_json" in device_group.attrs:
                raw = self.decode_if_bytes(device_group.attrs["capture_json"])
                capture = json.loads(raw)
                return self.normalise_capture_settings(capture)

            if "captures_json" in device_group.attrs:
                raw = self.decode_if_bytes(device_group.attrs["captures_json"])
                captures = json.loads(raw)

                if len(captures) == 0:
                    return None

                if len(captures) > 1:
                    raise RuntimeError(
                        "This first PicoScope worker only supports one capture per shot."
                    )

                return self.normalise_capture_settings(captures[0])

            if "CAPTURE" in device_group:
                capture_obj = device_group["CAPTURE"]
                attrs = capture_obj.attrs

                capture = {}
                for key in attrs.keys():
                    capture[key] = self.decode_if_bytes(attrs[key])

                return self.normalise_capture_settings(capture)

        return None

    # -----------------------------------------------------------------------
    # Helper method: normalise_capture_settings
    #
    # Makes sure the capture dictionary has all required keys, gives reasonable
    # defaults, and converts values from HDF5-friendly types into normal Python
    # types.
    # -----------------------------------------------------------------------
    def normalise_capture_settings(self, capture):
        if capture is None:
            return None

        capture = dict(capture)

        if "name" not in capture:
            capture["name"] = "trace"

        if "channels" not in capture:
            capture["channels"] = ["A"]

        channels = capture["channels"]

        if isinstance(channels, str):
            # Accept "A,B,C" or "ABC" or "A".
            if "," in channels:
                channels = [ch.strip() for ch in channels.split(",")]
            else:
                channels = list(channels)

        channels = [self.normalise_channel(ch) for ch in channels]

        trigger_channel = capture.get("trigger_channel", "D")
        trigger_channel = self.normalise_channel(trigger_channel)

        capture["channels"] = channels
        capture["trigger_channel"] = trigger_channel
        capture["trigger_threshold_V"] = float(capture.get("trigger_threshold_V", 1.0))
        capture["trigger_direction"] = str(capture.get("trigger_direction", "rising"))
        capture["sample_rate_Hz"] = float(capture.get("sample_rate_Hz", 5e6))
        capture["pre_trigger_s"] = float(capture.get("pre_trigger_s", 0.0))
        capture["post_trigger_s"] = float(capture.get("post_trigger_s", 1e-3))
        capture["voltage_range"] = self.normalise_range(
            capture.get("voltage_range", "5V")
        )
        capture["coupling"] = str(capture.get("coupling", "DC")).upper()
        capture["auto_trigger_ms"] = int(capture.get("auto_trigger_ms", 0))
        capture["acquisition_timeout_s"] = float(
            capture.get("acquisition_timeout_s", 10.0)
        )

        if capture["sample_rate_Hz"] <= 0:
            raise ValueError("sample_rate_Hz must be positive.")

        if capture["pre_trigger_s"] < 0:
            raise ValueError("pre_trigger_s must be >= 0.")

        if capture["post_trigger_s"] <= 0:
            raise ValueError("post_trigger_s must be > 0.")

        if len(capture["channels"]) == 0:
            raise ValueError("At least one PicoScope channel must be saved.")

        return capture

    # -----------------------------------------------------------------------
    # Helper method: ready_acquisition
    #
    # Configures the scope and arms block capture.
    #
    # This is the PicoScope equivalent of the NICounter ready_acquisition()
    # method. It prepares the device, but the actual acquisition waits for the
    # hardware trigger.
    # -----------------------------------------------------------------------
    def ready_acquisition(self):
        capture = self.capture

        requested_sample_rate_Hz = capture["sample_rate_Hz"]
        pre_trigger_s = capture["pre_trigger_s"]
        post_trigger_s = capture["post_trigger_s"]

        saved_channels = list(capture["channels"])
        trigger_channel = capture["trigger_channel"]

        # The trigger channel must be enabled even if we do not save it.
        enabled_channels = sorted(
            set(saved_channels + [trigger_channel]),
            key=lambda ch: ["A", "B", "C", "D"].index(ch),
        )

        ps.ps2000aStop(self.handle)

        for channel in ["A", "B", "C", "D"]:
            enabled = channel in enabled_channels
            self.set_channel(
                channel=channel,
                enabled=enabled,
                voltage_range=capture["voltage_range"],
                coupling=capture["coupling"],
            )

        self.timebase, self.time_interval_ns = self.choose_timebase(
            requested_sample_rate_Hz=requested_sample_rate_Hz,
            pre_trigger_s=pre_trigger_s,
            post_trigger_s=post_trigger_s,
        )

        actual_dt_s = self.time_interval_ns * 1e-9

        self.pre_trigger_samples = int(round(pre_trigger_s / actual_dt_s))
        self.post_trigger_samples = int(round(post_trigger_s / actual_dt_s))
        self.total_samples = self.pre_trigger_samples + self.post_trigger_samples

        if self.total_samples <= 0:
            raise RuntimeError("PicoScope total_samples calculated as zero.")

        self.set_simple_trigger(
            channel=trigger_channel,
            threshold_V=capture["trigger_threshold_V"],
            voltage_range=capture["voltage_range"],
            direction=capture["trigger_direction"],
            auto_trigger_ms=capture["auto_trigger_ms"],
        )

        self.adc_buffers = {}
        for channel in saved_channels:
            buffer_type = ctypes.c_int16 * self.total_samples
            self.adc_buffers[channel] = {
                "max": buffer_type(),
                "min": buffer_type(),
            }
            self.channel_ranges[channel] = capture["voltage_range"]

        oversample = ctypes.c_int16(0)

        status = ps.ps2000aRunBlock(
            self.handle,
            self.pre_trigger_samples,
            self.post_trigger_samples,
            self.timebase,
            oversample,
            None,
            0,
            None,
            None,
        )
        assert_pico_ok(status)

        print(
            "PicoScope armed: "
            f"{self.total_samples} samples, "
            f"dt = {self.time_interval_ns:.6g} ns, "
            f"trigger = Ch {trigger_channel}"
        )

    # -----------------------------------------------------------------------
    # Helper method: wait_until_ready
    #
    # Polls the PicoScope until the block capture has completed.
    #
    # If the trigger cable is missing or the threshold is wrong, this will time
    # out and raise an error rather than hanging BLACS forever.
    # -----------------------------------------------------------------------
    def wait_until_ready(self, timeout_s):
        ready = ctypes.c_int16(0)
        t0 = time.time()

        while not ready.value:
            status = ps.ps2000aIsReady(self.handle, ctypes.byref(ready))
            assert_pico_ok(status)

            if time.time() - t0 > timeout_s:
                ps.ps2000aStop(self.handle)
                raise RuntimeError(
                    "PicoScope acquisition timed out. "
                    "Check that the trigger cable is connected, the trigger "
                    "channel is correct, and the trigger threshold is reasonable."
                )

            time.sleep(0.01)

    # -----------------------------------------------------------------------
    # Helper method: read_block_data
    #
    # Assigns PicoSDK data buffers, reads the waveform from the PicoScope, and
    # converts ADC counts into volts.
    # -----------------------------------------------------------------------
    def read_block_data(self):
        for channel, buffers in self.adc_buffers.items():
            status = ps.ps2000aSetDataBuffers(
                self.handle,
                self.channel_enum(channel),
                ctypes.byref(buffers["max"]),
                ctypes.byref(buffers["min"]),
                self.total_samples,
                0,
                self.ratio_mode_none(),
            )
            assert_pico_ok(status)

        c_total_samples = ctypes.c_int32(self.total_samples)
        overflow = ctypes.c_int16()

        status = ps.ps2000aGetValues(
            self.handle,
            0,
            ctypes.byref(c_total_samples),
            0,
            self.ratio_mode_none(),
            0,
            ctypes.byref(overflow),
        )
        assert_pico_ok(status)

        self.last_overflow = overflow.value

        n_samples = c_total_samples.value
        traces_V = {}

        for channel, buffers in self.adc_buffers.items():
            voltage_range_enum = self.range_enum(self.channel_ranges[channel])

            values_mV = adc2mV(
                buffers["max"],
                voltage_range_enum,
                self.max_adc,
            )

            values_V = np.asarray(values_mV[:n_samples], dtype=np.float64) * 1e-3
            traces_V[channel] = values_V

        return traces_V

    # -----------------------------------------------------------------------
    # Helper method: make_time_axis_s
    #
    # Builds a time axis in seconds.
    #
    # The trigger point is placed at t = 0. Pre-trigger samples are negative
    # time; post-trigger samples are positive time.
    # -----------------------------------------------------------------------
    def make_time_axis_s(self):
        dt_s = self.time_interval_ns * 1e-9
        sample_indices = np.arange(self.total_samples, dtype=np.float64)
        time_s = (sample_indices - self.pre_trigger_samples) * dt_s
        return time_s

    # -----------------------------------------------------------------------
    # Helper method: choose_timebase
    #
    # Finds a PicoScope timebase whose time interval is close to the requested
    # sample rate.
    #
    # The PicoSDK does not take sample_rate_Hz directly in block mode. Instead,
    # you give it a timebase index. We ask the SDK what interval each timebase
    # gives and choose the closest valid one.
    # -----------------------------------------------------------------------
    def choose_timebase(self, requested_sample_rate_Hz, pre_trigger_s, post_trigger_s):
        target_dt_ns = 1e9 / requested_sample_rate_Hz
        approximate_total_samples = max(
            1,
            int(round((pre_trigger_s + post_trigger_s) * requested_sample_rate_Hz)),
        )

        best = None
        oversample = ctypes.c_int16(0)

        for timebase in range(0, 10000):
            time_interval_ns = ctypes.c_float()
            returned_max_samples = ctypes.c_int32()

            status = ps.ps2000aGetTimebase2(
                self.handle,
                timebase,
                approximate_total_samples,
                ctypes.byref(time_interval_ns),
                oversample,
                ctypes.byref(returned_max_samples),
                0,
            )

            if status != 0:
                continue

            interval = float(time_interval_ns.value)
            error = abs(interval - target_dt_ns)

            if best is None or error < best["error"]:
                best = {
                    "timebase": timebase,
                    "interval_ns": interval,
                    "error": error,
                    "max_samples": returned_max_samples.value,
                }

            if error == 0:
                break

        if best is None:
            raise RuntimeError(
                "Could not find a valid PicoScope timebase. "
                "Try lowering sample_rate_Hz or disabling unused channels."
            )

        actual_dt_s = best["interval_ns"] * 1e-9
        actual_total_samples = int(
            round((pre_trigger_s + post_trigger_s) / actual_dt_s)
        )

        if actual_total_samples > best["max_samples"]:
            raise RuntimeError(
                "Requested PicoScope capture is too long for the selected timebase. "
                f"Requested {actual_total_samples} samples, "
                f"but SDK reported max {best['max_samples']}."
            )

        print(
            "PicoScope timebase selected: "
            f"timebase={best['timebase']}, "
            f"dt={best['interval_ns']:.6g} ns, "
            f"requested dt={target_dt_ns:.6g} ns"
        )

        return best["timebase"], best["interval_ns"]

    # -----------------------------------------------------------------------
    # Helper method: set_channel
    #
    # Enables or disables a PicoScope analog channel and sets coupling/range.
    # -----------------------------------------------------------------------
    def set_channel(self, channel, enabled, voltage_range, coupling):
        status = ps.ps2000aSetChannel(
            self.handle,
            self.channel_enum(channel),
            int(enabled),
            self.coupling_enum(coupling),
            self.range_enum(voltage_range),
            0,
        )
        assert_pico_ok(status)

    # -----------------------------------------------------------------------
    # Helper method: set_simple_trigger
    #
    # Configures a simple edge trigger on one PicoScope analog input channel.
    #
    # The trigger input is still a normal analog waveform channel. The PicoScope
    # just watches that channel and starts acquisition when it crosses the
    # specified threshold.
    # -----------------------------------------------------------------------
    def set_simple_trigger(
        self,
        channel,
        threshold_V,
        voltage_range,
        direction,
        auto_trigger_ms,
    ):
        threshold_mV = threshold_V * 1000.0

        threshold_adc = int(
            mV2adc(
                threshold_mV,
                self.range_enum(voltage_range),
                self.max_adc,
            )
        )

        status = ps.ps2000aSetSimpleTrigger(
            self.handle,
            1,
            self.channel_enum(channel),
            threshold_adc,
            self.direction_enum(direction),
            0,
            int(auto_trigger_ms),
        )
        assert_pico_ok(status)

    # -----------------------------------------------------------------------
    # Helper method: clear_shot_state
    #
    # Clears all shot-specific variables after a completed or aborted shot.
    # -----------------------------------------------------------------------
    def clear_shot_state(self):
        self.h5_filepath = None
        self.capture = None
        self.timebase = None
        self.time_interval_ns = None
        self.pre_trigger_samples = None
        self.post_trigger_samples = None
        self.total_samples = None
        self.adc_buffers = {}
        self.channel_ranges = {}

    # -----------------------------------------------------------------------
    # Helper method: channel_enum
    #
    # Converts "A", "B", "C", "D" into PicoSDK channel constants.
    # -----------------------------------------------------------------------
    def channel_enum(self, channel):
        channel = self.normalise_channel(channel)

        table = {
            "A": "PS2000A_CHANNEL_A",
            "B": "PS2000A_CHANNEL_B",
            "C": "PS2000A_CHANNEL_C",
            "D": "PS2000A_CHANNEL_D",
        }

        try:
            return ps.PS2000A_CHANNEL[table[channel]]
        except Exception:
            fallback = {"A": 0, "B": 1, "C": 2, "D": 3}
            return fallback[channel]

    # -----------------------------------------------------------------------
    # Helper method: range_enum
    #
    # Converts "5V", "2V", etc. into PicoSDK voltage-range constants.
    # -----------------------------------------------------------------------
    def range_enum(self, voltage_range):
        voltage_range = self.normalise_range(voltage_range)

        table = {
            "10MV": "PS2000A_10MV",
            "20MV": "PS2000A_20MV",
            "50MV": "PS2000A_50MV",
            "100MV": "PS2000A_100MV",
            "200MV": "PS2000A_200MV",
            "500MV": "PS2000A_500MV",
            "1V": "PS2000A_1V",
            "2V": "PS2000A_2V",
            "5V": "PS2000A_5V",
            "10V": "PS2000A_10V",
            "20V": "PS2000A_20V",
            "50V": "PS2000A_50V",
        }

        if voltage_range not in table:
            raise ValueError(f"Unsupported PicoScope voltage range: {voltage_range}")

        return ps.PS2000A_RANGE[table[voltage_range]]

    # -----------------------------------------------------------------------
    # Helper method: coupling_enum
    #
    # Converts "DC" or "AC" into PicoSDK coupling constants.
    # -----------------------------------------------------------------------
    def coupling_enum(self, coupling):
        coupling = str(coupling).upper()

        if coupling == "DC":
            try:
                return ps.PS2000A_COUPLING["PS2000A_DC"]
            except Exception:
                return 1

        if coupling == "AC":
            try:
                return ps.PS2000A_COUPLING["PS2000A_AC"]
            except Exception:
                return 0

        raise ValueError(f"Unsupported PicoScope coupling: {coupling}")

    # -----------------------------------------------------------------------
    # Helper method: direction_enum
    #
    # Converts trigger direction strings into PicoSDK constants.
    # -----------------------------------------------------------------------
    def direction_enum(self, direction):
        direction = str(direction).strip().upper()

        table = {
            "RISING": "PS2000A_RISING",
            "FALLING": "PS2000A_FALLING",
            "ABOVE": "PS2000A_ABOVE",
            "BELOW": "PS2000A_BELOW",
        }

        if direction not in table:
            raise ValueError(f"Unsupported trigger direction: {direction}")

        try:
            return ps.PS2000A_THRESHOLD_DIRECTION[table[direction]]
        except Exception:
            fallback = {
                "ABOVE": 0,
                "BELOW": 1,
                "RISING": 2,
                "FALLING": 3,
            }
            return fallback[direction]

    # -----------------------------------------------------------------------
    # Helper method: ratio_mode_none
    #
    # Returns the PicoSDK constant for no downsampling.
    # -----------------------------------------------------------------------
    def ratio_mode_none(self):
        try:
            return ps.PS2000A_RATIO_MODE["PS2000A_RATIO_MODE_NONE"]
        except Exception:
            return 0

    # -----------------------------------------------------------------------
    # Helper method: normalise_channel
    #
    # Converts byte/string/numpy channel labels into one of "A", "B", "C", "D".
    # -----------------------------------------------------------------------
    def normalise_channel(self, channel):
        channel = self.decode_if_bytes(channel)
        channel = str(channel).strip().upper()

        if channel.startswith("CHANNEL_"):
            channel = channel.replace("CHANNEL_", "")

        if channel.startswith("CH"):
            channel = channel.replace("CH", "")

        if channel not in ["A", "B", "C", "D"]:
            raise ValueError(f"Invalid PicoScope channel: {channel}")

        return channel

    # -----------------------------------------------------------------------
    # Helper method: normalise_range
    #
    # Converts range strings into a compact form like "5V" or "500MV".
    # -----------------------------------------------------------------------
    def normalise_range(self, voltage_range):
        voltage_range = self.decode_if_bytes(voltage_range)
        voltage_range = str(voltage_range).strip().upper()
        voltage_range = voltage_range.replace(" ", "")
        voltage_range = voltage_range.replace("PS2000A_", "")
        voltage_range = voltage_range.replace("MILLIVOLT", "MV")
        voltage_range = voltage_range.replace("MVOLT", "MV")
        voltage_range = voltage_range.replace("VOLT", "V")

        return voltage_range

    # -----------------------------------------------------------------------
    # Helper method: decode_if_bytes
    #
    # HDF5 attributes often come back as bytes or numpy arrays. This converts
    # the common cases into normal Python strings/lists.
    # -----------------------------------------------------------------------
    def decode_if_bytes(self, value):
        if isinstance(value, bytes):
            return value.decode(errors="replace")

        if isinstance(value, np.bytes_):
            return value.decode(errors="replace")

        if isinstance(value, np.ndarray):
            if value.dtype.kind in ["S", "O", "U"]:
                return [self.decode_if_bytes(item) for item in value.tolist()]
            return value.tolist()

        return value
    # -----------------------------------------------------------------------
    # GUI method: start_display
    #
    # enables live acquisition and defines default scope-screen settings
    # -----------------------------------------------------------------------
    def start_display(self):
        if self.capture is not None:
            raise RuntimeError(
                "Cannot start live display while a shot capture is active."
            )

        self.display_running = True
        return True
    
    # -----------------------------------------------------------------------
    # GUI method: get_display_waveform
    #
    # performs one short, auto-triggered block capture and returns it to the GUI
    # -----------------------------------------------------------------------

    def get_display_waveform(self):
        if not self.display_running:
            return None

        # Settings for one frame of the live display.
        self.capture = self.normalise_capture_settings(
            {
                "name": "live_display",
                "channels": ["A", "B", "C", "D"],
                "trigger_channel": "A",
                "trigger_threshold_V": 0.0,
                "trigger_direction": "rising",
                "sample_rate_Hz": 1e6,
                "pre_trigger_s": 5e-3,
                "post_trigger_s": 5e-3,
                "voltage_range": "5V",
                "coupling": "DC",

                # This is important for a free-running display. If no edge is
                # detected, the scope automatically captures after 100 ms.
                "auto_trigger_ms": 100,
                "acquisition_timeout_s": 1.0,
            }
        )

        try:
            self.ready_acquisition()
            self.wait_until_ready(timeout_s=1.0)

            traces_V = self.read_block_data()
            time_s = self.make_time_axis_s()

            status = ps.ps2000aStop(self.handle)
            assert_pico_ok(status)

            # Limit how much data is sent through BLACS IPC.
            maximum_display_points = 4000
            stride = max(1, len(time_s) // maximum_display_points)

            return {
                "time": time_s[::stride],
                "channels": {
                    channel: values[::stride]
                    for channel, values in traces_V.items()
                },
                "sample_rate": 1e9 / self.time_interval_ns,
                "overflow": int(getattr(self, "last_overflow", 0)),
            }

        finally:
            self.capture = None
            self.timebase = None
            self.time_interval_ns = None
            self.pre_trigger_samples = None
            self.post_trigger_samples = None
            self.total_samples = None
            self.adc_buffers = {}
            self.channel_ranges = {}

    # -----------------------------------------------------------------------
    # GUI method: stop_display
    #
    # stops the live display 
    # -----------------------------------------------------------------------
    def stop_display(self):
        self.display_running = False

        try:
            status = ps.ps2000aStop(self.handle)
            assert_pico_ok(status)
        finally:
            self.clear_shot_state()

        return True