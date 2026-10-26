"""Measure MOT fluorescence after a variable loading time.

Runmanager global: mot_loading_time (seconds), in mot_globals.h5 / timing.
Set a scalar for one loading time or an array to scan loading times. Keep
mot_gradient_setpoint, mot_amp_setpoint, and repump_amp_setpoint fixed for
a loading curve at one set of trap parameters.

Both beams and shutters stay ON throughout the background/signal pair.
The gradient is OFF for 0.7 s before the background images. After 50 ms
for the 1 ms background exposures and camera recovery, the gradient turns
ON. This coil-on command defines loading t=0. Both cameras take the MOT
images mot_loading_time seconds later, with the same exposure and gain.
The physical field rise time is not measured by this sequence.

Images retain the Imaging_MOT.py paths:
  images/imaq_cam1/flir_camera_images/cam1_background and cam1_signal
  images/imaq_cam2/flir_camera_images/cam2_background and cam2_signal
Each camera's saved mot_on_time, background_time, and signal_time give
the absolute shot times. The coil and both beams remain ON after the shot.
"""

# Device names and Runmanager globals are provided by labscript.
# pylint: disable=undefined-variable
# pyright: reportUndefinedVariable=false

import math

import labscript as lab
from labscriptlib.imaq_lab.connection_table import ConnectionTable


CLOUD_CLEAR_TIME = 0.7
CAMERA_RECOVERY_TIME = 50e-3
TRIGGER_DURATION = 2e-3
FINAL_CLOCK_MARGIN = 10e-3


def main():
    loading_time = float(mot_loading_time)
    if not math.isfinite(loading_time) or loading_time < 0.0:
        raise ValueError('mot_loading_time must be finite and nonnegative (seconds).')

    ConnectionTable()
    background_time = CLOUD_CLEAR_TIME
    mot_on_time = background_time + CAMERA_RECOVERY_TIME
    signal_time = mot_on_time + loading_time
    readout_done = signal_time + CAMERA_RECOVERY_TIME
    shot_end = readout_done + FINAL_CLOCK_MARGIN

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

    lab.start()
    mot_aom_analog.constant(0.0, mot_amp_setpoint)
    repumper_aom_analog.constant(0.0, repump_amp_setpoint)
    mot_shutter_do.go_high(0.0)
    repumper_shutter_do.go_high(0.0)
    mot_gradient_analog.constant(0.0, 0.0)
    lab.add_time_marker(0.0, 'Coil OFF: clear cloud for 0.7 s; both beams ON')

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
        # At zero loading time the image shares the coil-on marker's time.
        lab.add_time_marker(signal_time, f'MOT images: loading time {loading_time:g} s')
    for index, camera in enumerate((imaq_cam1, imaq_cam2), 1):
        camera.expose(
            t=signal_time,
            name='flir_camera_images',
            frametype=f'cam{index}_signal',
            trigger_duration=TRIGGER_DURATION,
        )

    # Reassert held values to provide enough clock ticks for the NI cards.
    # The digital card requires at least four buffered samples. These
    # commands keep the shutters open and add no optical switching edges.
    for sample_time in (background_time, mot_on_time, readout_done):
        mot_shutter_do.go_high(sample_time)
    mot_gradient_analog.constant(readout_done, mot_gradient_setpoint)

    lab.stop(shot_end)
    print(
        f'Background at {background_time:.6f} s; coil ON at {mot_on_time:.6f} s; '
        f'MOT images at {signal_time:.6f} s '
        f'(loading time {loading_time:.6f} s); shot ends at {shot_end:.6f} s'
    )


if __name__ == '__main__':
    main()
