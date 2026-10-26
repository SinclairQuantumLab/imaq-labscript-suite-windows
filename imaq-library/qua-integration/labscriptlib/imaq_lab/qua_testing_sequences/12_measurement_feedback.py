"""Measure on LF-FEM slot 3 AI1, then choose NI timing and OPX AO3 gain.

Detector input: con1 / LF-FEM 3 / analog input 1 (not digital output 1).
Readout uses existing scope_analog element/AO3 with a ZERO drive waveform.
Threshold is illustrative in integrated QUA units; calibrate for your detector.
No hardware has been executed for this proposed example.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from labscript import stop
from qm import qua
from user_devices.opx.tick_playback_types import TimeDilationPolicy
from opx_configuration import READOUT_ELEMENT, SCOPE_ANALOG
from sequence_support import (
    setup, begin, section, finish, wait_seconds, wait_runtime_seconds,
)

THRESHOLD = 0
ct, playbacks = setup()
for handle in ("detector_value", "selected_dilation", "selected_gain"):
    ct.opx_main.add_result_trace(
        handle=handle, trace_name=handle, sample_period=0.0,
        timestamp_handle=f"{handle}_times", timestamp_scale=4e-9,
    )


def build_program():
    with qua.program() as program:
        begin(ct, playbacks)
        value = qua.declare(qua.fixed)
        scale = qua.declare(qua.fixed)
        gain = qua.declare(qua.fixed)
        values = qua.declare_output_stream()
        times = qua.declare_output_stream()
        scales = qua.declare_output_stream()
        gains = qua.declare_output_stream()

        # Establish NI states before measuring. All relevant elements are aligned
        # by section() on exit, before the feedback branch and next replay.
        with section(ct, playbacks, "prepare_and_measure", 0.0, 0.125):
            wait_seconds(0.0625, READOUT_ELEMENT)
            qua.measure(
                "read", READOUT_ELEMENT,
                qua.integration.full("ones", value, "out1"),
                timestamp_stream=times,
            )
            qua.save(value, values)

        with qua.if_(value > THRESHOLD):
            qua.assign(scale, 2.0)
            qua.assign(gain, 0.5)
        with qua.else_():
            qua.assign(scale, 0.01)
            qua.assign(gain, 1.0)
        qua.save(scale, scales)
        qua.save(gain, gains)

        t0 = 0.125
        with section(
            ct, playbacks, "adaptive", t0, 1.0,
            time_dilation_policy=TimeDilationPolicy.qua_logic,
            qua_var_time_dilation=scale,
        ):
            ct.c1_AO30.constant(t0, 0.0)
            ct.c2_AO0.constant(t0, 0.0)
            ct.do0.go_low(t0)
            ct.c1_AO30.ramp(t0 + 0.125, 0.5, 0.0, 0.2, samplerate=1000)
            ct.c1_AO30.constant(t0 + 0.625, 0.2)
            ct.c1_AO30.constant(t0 + 0.75, 0.0)
            ct.c2_AO0.ramp(t0 + 0.125, 0.125, 0.0, 1.0, samplerate=1000)
            ct.c2_AO0.constant(t0 + 0.25, 1.0)
            ct.c2_AO0.constant(t0 + 0.625, 0.2)
            ct.c2_AO0.constant(t0 + 0.75, 0.0)
            ct.do0.go_high(t0 + 0.125)
            ct.do0.go_low(t0 + 0.625)
            # Scale the OPX delay explicitly. The 100 us pulse width stays fixed.
            wait_runtime_seconds(0.125, scale, SCOPE_ANALOG)
            qua.play("pulse" * qua.amp(gain), SCOPE_ANALOG)
            # Preserve the entire scaled section, including final zero/low hold.
            wait_runtime_seconds(1.0, scale)

        finish(playbacks)
        # The shared finish() saves clock streams; add experiment result streams here.
        with qua.stream_processing():
            values.save_all("detector_value")
            times.save_all("detector_value_times")
            times.save_all("selected_dilation_times")
            times.save_all("selected_gain_times")
            scales.save_all("selected_dilation")
            gains.save_all("selected_gain")
    return program


ct.opx_main.set_qua_program_builder(build_program)
stop(1.125)  # Nominal time; physical ~0.125 + scale*1.0 + guard, plus overhead.
