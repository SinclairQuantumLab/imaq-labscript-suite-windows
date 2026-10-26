"""The original MOT loading measurement, clocked by the master OPX with QUA.

Runmanager globals: mot_loading_time (seconds), mot_gradient_setpoint,
mot_amp_setpoint, and repump_amp_setpoint. Scan mot_loading_time with, for
example, np.linspace(0, 5, 26); hold the three setpoints fixed.

Both beams and shutters stay on. Clear the cloud with the gradient off for
0.7 s, take the background images, wait 50 ms, then turn the gradient on.
Take the signal images mot_loading_time seconds after that coil-on command.
The final gradient and beam values match the original sequence.

QUA only supplies the three NI sample clocks, with fixed dilation 1.0.
There are no detector-feedback branches or test voltage ramps. Identical
held samples every 62.5 ms keep NI clock waits short and provide enough
buffered samples. Recorded OPX tick timestamps allow runtime timing checks;
they describe the clock commands, not the physical coil rise time.
"""

import math
from pathlib import Path
import sys

# Match the helper's import name used by the other QUA shots. Runmanager reuses
# its compiler process and rejects importing one file under two module names.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'qua_testing_sequences'))

import labscript as lab
from qm import qua

from labscriptlib.imaq_lab.connection_table import ConnectionTable
from opx_configuration import (
    CLOCK_ELEMENTS,
    TICK_NS,
    make_config,
)
from user_devices.opx.qua_tick_programs import qua_section


# Device names and Runmanager globals are supplied through Labscript builtins.
# pylint: disable=undefined-variable
# pyright: reportUndefinedVariable=false

CLOUD_CLEAR_TIME = 0.7
CAMERA_RECOVERY_TIME = 50e-3
TRIGGER_DURATION = 2e-3
FINAL_CLOCK_MARGIN = 10e-3
CLOCK_SAMPLE_PERIOD = 0.0625
COMPLETION_GUARD_CYCLES = 250_000  # 1 ms; NI finite-task completion edge.


def main():
    loading_time = float(mot_loading_time)
    if not math.isfinite(loading_time) or loading_time < 0.0:
        raise ValueError('mot_loading_time must be finite and nonnegative (seconds).')
    if abs(round(loading_time / 4e-9) * 4e-9 - loading_time) > 1e-12:
        raise ValueError('mot_loading_time must lie on the OPX 4 ns timing grid.')

    background_time = CLOUD_CLEAR_TIME
    mot_on_time = background_time + CAMERA_RECOVERY_TIME
    signal_time = mot_on_time + loading_time
    readout_done = signal_time + CAMERA_RECOVERY_TIME
    shot_end = readout_done + FINAL_CLOCK_MARGIN

    ConnectionTable()
    opx_main.qm_config = make_config()
    opx_main.set_execution_mode('execute')
    clock_lines = {
        'analog': ni_pxie_6738_1_clock,
        'analog2': ni_pxie_6738_2_clock,
        'digital': ni_pxie_6535_clock,
    }
    playbacks = {}
    for label, line in clock_lines.items():
        stream_name = f'mot_loading_{label}_tick_times'
        playbacks[label] = opx_main.enable_inline_tick_playback(
            tick_element=CLOCK_ELEMENTS[label],
            tick_operation='tick',
            tick_pulse_cycles=TICK_NS // 4,
            default_time_dilation=1.0,
            timestamp_stream_name=stream_name,
            clock_line=line,
        )
        opx_main.add_result_trace(
            handle=f'{stream_name}_values',
            trace_name=f'mot_loading_{label}_ticks',
            sample_period=0.0,
            timestamp_handle=stream_name,
            timestamp_scale=4e-9,
            clock_line=line,
        )
        opx_main.add_result_trace(
            handle=f'mot_loading_{label}_completion_times',
            trace_name=f'mot_loading_{label}_completion_cycles',
            sample_period=0.0,
            clock_line=line,
        )

    for camera in (imaq_cam1, imaq_cam2):
        attributes = dict(camera.camera_attributes)
        exposure_us = float(attributes['AcquisitionControl::ExposureTime'])
        if not math.isclose(exposure_us, 1000.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError(f'{camera.name}: this shot requires a programmed 1 ms exposure.')
        if attributes['AcquisitionControl::ExposureMode'] != 'Timed':
            raise ValueError(f'{camera.name}: this shot requires Timed exposure mode.')

        trigger_mode = attributes.pop('AcquisitionControl::TriggerMode')
        attributes['AcquisitionControl::ExposureAuto'] = 'Off'
        attributes['AnalogControl::GainAuto'] = 'Off'
        attributes['AcquisitionControl::AcquisitionFrameRateEnable'] = False
        attributes['AcquisitionControl::TriggerMode'] = trigger_mode
        camera.camera_attributes = attributes
        camera.set_property(
            'camera_attributes', attributes, 'device_properties', overwrite=True,
        )
        for name, value in {
            'mot_loading_time': loading_time,
            'mot_on_time': mot_on_time,
            'background_time': background_time,
            'signal_time': signal_time,
        }.items():
            camera.set_property(name, value, 'device_properties')

    # Record all apparatus instructions once. The builder below only emits QUA.
    lab.start()
    repumper_aom_analog.constant(0.0, repump_amp_setpoint)
    repumper_shutter_do.go_high(0.0)
    mot_gradient_analog.constant(0.0, 0.0)
    lab.add_time_marker(0.0, 'Coil OFF: clear cloud for 0.7 s; both beams ON')

    # Reassert held states without introducing optical or voltage changes.
    # Each NI clock gap is <=62.5 ms, below 2**24 OPX clock cycles. These
    # samples also satisfy the PXIe-6535's initial transfer requirement.
    hold_times = [
        index * CLOCK_SAMPLE_PERIOD
        for index in range(math.floor(readout_done / CLOCK_SAMPLE_PERIOD) + 1)
    ]
    if not math.isclose(hold_times[-1], readout_done, rel_tol=0.0, abs_tol=1e-12):
        hold_times.append(readout_done)
    for sample_time in hold_times:
        mot_aom_analog.constant(sample_time, mot_amp_setpoint)
        mot_shutter_do.go_high(sample_time)
        c2_AO0.constant(sample_time, c2_AO0.default_value)

    lab.add_time_marker(background_time, 'Background images: coil OFF')
    for index, camera in enumerate((imaq_cam1, imaq_cam2), 1):
        camera.expose(
            t=background_time,
            name='flir_camera_images',
            frametype=f'cam{index}_background',
            trigger_duration=TRIGGER_DURATION,
        )

    mot_gradient_analog.constant(mot_on_time, mot_gradient_setpoint)
    lab.add_time_marker(mot_on_time, 'Coil ON: loading t=0')
    if loading_time > 0.0:
        lab.add_time_marker(signal_time, f'MOT images: loading time {loading_time:g} s')
    for index, camera in enumerate((imaq_cam1, imaq_cam2), 1):
        camera.expose(
            t=signal_time,
            name='flir_camera_images',
            frametype=f'cam{index}_signal',
            trigger_duration=TRIGGER_DURATION,
        )
    mot_gradient_analog.constant(readout_done, mot_gradient_setpoint)

    def build_program():
        with qua.program() as program:
            for playback in playbacks.values():
                playback.qua_prepare_tick_playback()
            with qua_section(
                opx_main, 'mot_loading', 0.0, shot_end,
                playback=list(playbacks.values()),
                pre_align=list(CLOCK_ELEMENTS.values()),
                post_align=list(CLOCK_ELEMENTS.values()),
                time_dilation=1.0,
            ):
                pass

            # The section replays every uploaded NI row, excluding stop(t).
            # Supply the separate completion edge used by the apparatus driver.
            completion_streams = {}
            for label, element in CLOCK_ELEMENTS.items():
                completion_streams[label] = qua.declare_output_stream()
                qua.wait(COMPLETION_GUARD_CYCLES, element)
                qua.play('tick', element, timestamp_stream=completion_streams[label])
            with qua.stream_processing():
                for playback in playbacks.values():
                    playback.save_tick_trace()
                for label, stream in completion_streams.items():
                    stream.save_all(f'mot_loading_{label}_completion_times')
        return program

    opx_main.set_qua_program_builder(build_program)
    lab.stop(shot_end)
    print(
        f'QUA fixed-clock MOT loading: background at {background_time:.6f} s; '
        f'coil ON at {mot_on_time:.6f} s; signal at {signal_time:.6f} s '
        f'(loading {loading_time:.6f} s); nominal stop {shot_end:.6f} s.'
    )


if __name__ == '__main__':
    main()
