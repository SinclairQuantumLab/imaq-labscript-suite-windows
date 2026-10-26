"""Track the MOT cloud's motion after switching off the gradient coil.

Keep the coil and both beams on for MOT_SETTLE_TIME before the loaded reference.
Turn the coil off one frame interval later, then acquire synchronized image
pairs at 50 fps for 0.6 s. The MOT laser and repumper remain at their normal
setpoints throughout: this measures motion with illumination still present.
There is no initial coil-off clearing step.

50 fps gives 20 ms sampling. Both cameras timed out at 125 fps; at 100 fps,
camera 1 received only 42 of 62 expected images while camera 2 completed.
Use this lower rate for the next hardware test; it is not yet verified.
Saved AcquisitionResultingFrameRate values about 143.9/166.7 fps were capacity
estimates, not proof of a successful paired burst. Check image counts and
failed_shot before increasing FRAME_RATE_HZ or changing ROIs. Recompile this
script: an existing queued H5 file retains its original trigger rate.
Keep the programmed 1 ms exposures and camera-specific trigger delays.

Each camera saves, under images/<camera>/mot_release/:
  loaded_cam1/2: a single loaded-cloud reference image;
  released_cam1/2: an ordered stack of 30 release images;
  background_cam1/2: a single image at 0.6 s with the coil still off.
The saved EXPOSURES table gives each programmed camera trigger time. Subtract
the camera device property mot_off_time to get time since the coil-off command.
Actual exposure starts may include camera-specific delay; mot_off_time also
does not measure the physical magnetic-field decay.

Use the reference/background and full image stacks to track cloud position
and size in each camera view, rather than reducing images to brightness alone.
The existing ROIs are retained; clouds can leave these image regions. Pixel
motion needs a spatial calibration to convert to speed in physical units.
"""

import math

from labscript import add_time_marker, start, stop
from labscriptlib.imaq_lab.connection_table import ConnectionTable


ConnectionTable()

MOT_SETTLE_TIME = 5.0
CAPTURE_DURATION = 0.6
FRAME_RATE_HZ = 50.0
TRIGGER_DURATION = 1e-3
READOUT_WAIT = 50e-3
MOT_RELOAD_TIME = 5.0

if not math.isfinite(FRAME_RATE_HZ) or FRAME_RATE_HZ <= 0.0:
    raise ValueError('FRAME_RATE_HZ must be finite and positive.')
if not math.isfinite(CAPTURE_DURATION) or CAPTURE_DURATION <= 0.0:
    raise ValueError('CAPTURE_DURATION must be finite and positive.')

FRAME_INTERVAL = 1.0 / FRAME_RATE_HZ
if FRAME_INTERVAL <= TRIGGER_DURATION:
    raise ValueError('Camera triggers must be separated by more than 1 ms.')

NUMBER_RELEASE_FRAMES = math.ceil(CAPTURE_DURATION * FRAME_RATE_HZ)
REFERENCE_TIME = MOT_SETTLE_TIME
MOT_OFF_TIME = REFERENCE_TIME + FRAME_INTERVAL
# Put the background on the same cadence, at or just beyond CAPTURE_DURATION.
BACKGROUND_TIME = MOT_OFF_TIME + NUMBER_RELEASE_FRAMES * FRAME_INTERVAL
MOT_RESTORE_TIME = BACKGROUND_TIME + READOUT_WAIT
SHOT_END = MOT_RESTORE_TIME + MOT_RELOAD_TIME + READOUT_WAIT

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
    for key, value in {
        'mot_off_time': MOT_OFF_TIME,
        'frame_interval': FRAME_INTERVAL,
        'frame_rate_hz': FRAME_RATE_HZ,
        'capture_duration': CAPTURE_DURATION,
        'release_frame_count': NUMBER_RELEASE_FRAMES,
        'loaded_reference_time': REFERENCE_TIME,
        'background_time': BACKGROUND_TIME,
        'mot_restore_time': MOT_RESTORE_TIME,
        'timing_reference': 'Programmed camera trigger minus coil-off command; '
                            'actual exposure and field-decay timing are not assumed.',
    }.items():
        camera.set_property(key, value, 'device_properties')

start()

# Begin with the MOT on and allow it to settle at the normal global setpoints.
mot_repumper_analog.constant(0.0, repump_amp_setpoint)
mot_laser_analog.constant(0.0, mot_amp_setpoint)
mot_gradient_amp.constant(0.0, mot_gradient_setpoint)
c2_AO_dummy.constant(0.0, 0.0)

add_time_marker(REFERENCE_TIME, 'Loaded MOT reference')
for index, camera in enumerate((imaq_cam1, imaq_cam2), 1):
    camera.expose(
        t=REFERENCE_TIME,
        name='mot_release',
        frametype=f'loaded_cam{index}',
        trigger_duration=TRIGGER_DURATION,
    )

add_time_marker(MOT_OFF_TIME, 'Coil off; rapid release imaging')
mot_gradient_amp.constant(MOT_OFF_TIME, 0.0)

# The first pair is triggered at the coil-off command. Both cameras retain
# their own exposure latency, so this is nominal t=0, not a field measurement.
for frame_index in range(NUMBER_RELEASE_FRAMES):
    frame_time = MOT_OFF_TIME + frame_index * FRAME_INTERVAL
    for index, camera in enumerate((imaq_cam1, imaq_cam2), 1):
        camera.expose(
            t=frame_time,
            name='mot_release',
            frametype=f'released_cam{index}',
            trigger_duration=TRIGGER_DURATION,
        )

# Same beams and camera settings after the cloud is expected to disappear.
add_time_marker(BACKGROUND_TIME, 'Late coil-off background')
for index, camera in enumerate((imaq_cam1, imaq_cam2), 1):
    camera.expose(
        t=BACKGROUND_TIME,
        name='mot_release',
        frametype=f'background_cam{index}',
        trigger_duration=TRIGGER_DURATION,
    )

add_time_marker(MOT_RESTORE_TIME, 'Restore MOT coil')
mot_gradient_amp.constant(MOT_RESTORE_TIME, mot_gradient_setpoint)

# Reload for the next shot; the unchanged dummy sample keeps AO buffering valid.
c2_AO_dummy.constant(MOT_RESTORE_TIME + MOT_RELOAD_TIME, 0.0)
stop(SHOT_END)
