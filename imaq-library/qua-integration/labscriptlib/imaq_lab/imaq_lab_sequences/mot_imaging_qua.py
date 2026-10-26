"""Measure on LF-FEM slot 3 AI1, then choose NI timing and OPX AO3 gain.

Detector input: con1 / LF-FEM 3 / analog input 1 (not digital output 1).
Readout uses existing scope_analog element/AO3 with a ZERO drive waveform.
Threshold is illustrative in integrated QUA units; calibrate for your detector.
No hardware has been executed for this proposed example.
"""
import sys
from pathlib import Path
import math
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "qua_testing_sequences"))
from labscript import stop
from qm import qua
from user_devices.opx.tick_playback_types import TimeDilationPolicy
from opx_configuration import READOUT_ELEMENT, SCOPE_ANALOG
from sequence_support import (
    setup, begin, section, finish, wait_seconds, wait_runtime_seconds,
)

THRESHOLD = 0
ct, playbacks = setup()
for handle in ("detector_value", "selected_dilation_1", "selected_dilation_2", "selected_gain"):
    ct.opx_main.add_result_trace(
        handle=handle, trace_name=handle, sample_period=0.0,
        timestamp_handle=f"{handle}_times", timestamp_scale=4e-9,
    )


def build_program():
    global signal_camera_exposure_start, background_camera_exposure_start
    with qua.program() as program:
        begin(ct, playbacks)


        for camera in (imaq_cam1, imaq_cam2):
            attributes = dict(camera.camera_attributes)
            exposure_us = float(attributes['AcquisitionControl::ExposureTime'])
            if not math.isclose(exposure_us, 1000.0, rel_tol=0.0, abs_tol=1e-6):
                raise ValueError(f'{camera.name}: this shot requires a programmed 1 ms exposure.')
            if attributes['AcquisitionControl::ExposureMode'] != 'Timed':
                raise ValueError(f'{camera.name}: this shot requires Timed exposure mode.')

            # Hardware triggers set the cadence. Keep each camera's gain value, ROI,
            # exposure, and trigger delay; disable automatic brightness adjustments.
            trigger_mode = attributes.pop('AcquisitionControl::TriggerMode')
            attributes['AnalogControl::GainAuto'] = 'Off'
            attributes['AcquisitionControl::AcquisitionFrameRateEnable'] = False
            attributes['AcquisitionControl::TriggerMode'] = trigger_mode
            camera.camera_attributes = attributes
            camera.set_property(
                'camera_attributes', attributes, 'device_properties', overwrite=True
            )    




        t_now = 0.0
        signal_camera_exposure_start = 0
        background_camera_exposure_start = 0
        value = qua.declare(qua.fixed)
        scale_1 = qua.declare(qua.fixed)
        scale_2 = qua.declare(qua.fixed)
        gain = qua.declare(qua.fixed)
        values = qua.declare_output_stream()
        times = qua.declare_output_stream()
        scales_1 = qua.declare_output_stream()
        scales_2 = qua.declare_output_stream()
        gains = qua.declare_output_stream()

        # Establish NI states before measuring. All relevant elements are aligned
        # by section() on exit, before the feedback branch and next replay.
        with section(ct, playbacks, "prepare_and_measure", t_now, 0.125):
            t_now += .0625
            wait_seconds(t_now, READOUT_ELEMENT)
            qua.measure(
                "read", READOUT_ELEMENT,
                qua.integration.full("ones", value, "out1"),
                timestamp_stream=times,
            )
            qua.save(value, values)
            t_now += 2e-6

        with qua.if_(value > THRESHOLD):
            qua.assign(scale_1, 1)
            qua.assign(scale_2, 1)
            qua.assign(gain, 0.5)
        with qua.else_():
            qua.assign(scale_1, 1)
            qua.assign(scale_2, 1)
            qua.assign(gain, 1.0)
        qua.save(scale_1, scales_1)
        qua.save(scale_2, scales_2)
        qua.save(gain, gains)

        t_now += .0625-2e-6
        signal_section_start = t_now
        print(t_now)
        
        with section(
            ct, playbacks, "adaptive signal", signal_section_start, 6.0,
            time_dilation_policy=TimeDilationPolicy.qua_logic,
            qua_var_time_dilation=scale_1,
        ):
            ct.c1_AO30.constant(t_now, 0.0)
            ct.c2_AO30.constant(t_now, 0.0)
            ct.do0.go_low(t_now)
            ct.mot_aom_analog.constant(t_now, mot_amp_setpoint)
            ct.repumper_aom_analog.constant(t_now,repump_amp_setpoint)
            ct.mot_gradient_analog.constant(t_now, mot_gradient_setpoint)
            t_now += mot_loading_time
            # ct.mot_aom_analog.constant(t_now+offset, 0.7)
            # ct.repumper_aom_analog.constant(t_now+offset, 0.7)
            # ct.mot_aom_analog.constant(t_now+offset + 1e-3, 0)
            # ct.repumper_aom_analog.constant(t_now+offset+1e-3,0)
            signal_camera_exposure_start = t_now
            ct.c1_AO30.ramp(t_now, 0.5, 0.0, 0.2, samplerate=1000)
            ct.c2_AO30.ramp(t_now, 0.125, 0.0, 1.0, samplerate=1000)
            ct.do0.go_high(t_now)
            t_now += 0.125
            ct.mot_gradient_analog.constant(t_now,0)
            ct.c2_AO30.constant(t_now + 0.25, 1.0)
            t_now += 0.375
            ct.c1_AO30.constant(t_now, 0.2)
            ct.c2_AO30.constant(t_now, 0.2)
            ct.do0.go_low(t_now)
            t_now += .125
            ct.c1_AO30.constant(t_now, 0.0)
            ct.c2_AO30.constant(t_now, 0.0)
            # Scale the OPX delay explicitly. The 100 us pulse width stays fixed.
            wait_runtime_seconds(t_now-signal_section_start, scale_1, SCOPE_ANALOG)
            qua.play("pulse" * qua.amp(gain), SCOPE_ANALOG)
            # Preserve the entire scaled section, including final zero/low hold.
            wait_runtime_seconds(1.0, scale_1)

        t_now = 6.125
        background_section_start = t_now
        with section(
            ct, playbacks, "adaptive background", background_section_start, 1.0,
            time_dilation_policy=TimeDilationPolicy.qua_logic,
            qua_var_time_dilation=scale_2,
        ):
            ct.c1_AO30.constant(t_now, 0.0)
            ct.c2_AO30.constant(t_now, 0.0)
            ct.do0.go_low(t_now)
            ct.mot_gradient_analog.constant(t_now,0)
            # ct.mot_aom_analog.constant(t_now, 0)
            # ct.repumper_aom_analog.constant(t_now,0)
            t_now += 0.250
            # ct.mot_aom_analog.constant(t_now+offset, 0.7)
            # ct.repumper_aom_analog.constant(t_now+offset, 0.7)
            background_camera_exposure_start = t_now
            ct.c1_AO30.ramp(t_now, 0.5, 0.0, 0.2, samplerate=1000)
            ct.c2_AO30.ramp(t_now, 0.125, 0.0, 1.0, samplerate=1000)
            ct.do0.go_high(t_now)
            t_now += 0.125
            # ct.mot_aom_analog.constant(t_now, 0)
            # ct.repumper_aom_analog.constant(t_now,0)
            ct.c2_AO30.constant(t_now + 0.25, 1.0)
            t_now += 0.375
            ct.c1_AO30.constant(t_now, 0.2)
            ct.c2_AO30.constant(t_now, 0.2)
            ct.do0.go_low(t_now)
            t_now += .125
            ct.c1_AO30.constant(t_now, 0.0)
            ct.c2_AO30.constant(t_now, 0.0)
            # Scale the OPX delay explicitly. The 100 us pulse width stays fixed.
            wait_runtime_seconds(t_now-background_section_start, scale_2, SCOPE_ANALOG)
            qua.play("pulse" * qua.amp(gain), SCOPE_ANALOG)
            # Preserve the entire scaled section, including final zero/low hold.
            wait_runtime_seconds(1.0, scale_2)


        finish(playbacks)
        # The shared finish() saves clock streams; add experiment result streams here.
        with qua.stream_processing():
            values.save_all("detector_value")
            times.save_all("detector_value_times")
            times.save_all("selected_dilation_1_times")
            times.save_all("selected_dilation_2_times")
            times.save_all("selected_gain_times")
            scales_1.save_all("selected_dilation_1")
            scales_2.save_all("selected_dilation_2")
            gains.save_all("selected_gain")
    return program


ct.opx_main.set_qua_program_builder(build_program)

ct.imaq_cam1.expose(
    t=signal_camera_exposure_start,
    name="flir_camera_images",
    frametype="cam1_signal",
    trigger_duration=2e-3,
)

ct.imaq_cam2.expose(
    t=signal_camera_exposure_start,
    name="flir_camera_images",
    frametype="cam2_signal",
    trigger_duration=2e-3,
)

ct.imaq_cam1.expose(
    t=background_camera_exposure_start,
    name="flir_camera_images",
    frametype="cam1_background",
    trigger_duration=2e-3,
)

ct.imaq_cam2.expose(
    t=background_camera_exposure_start,
    name="flir_camera_images",
    frametype="cam2_background",
    trigger_duration=2e-3,
)

stop(7.5)  # Nominal time; physical ~0.125 + scale*1.0 + guard, plus overhead.
