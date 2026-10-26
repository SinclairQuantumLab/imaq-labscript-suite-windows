"""Take one MOT image pair per ten-minute shot; queue 72 shots for 12 hours.

In Runmanager, load MOT_long_term_monitor_repeats.h5 alongside the usual
experiment globals and enable its MOT_monitor_repeats group. Keep all MOT
setpoints fixed and use only monitor_index as the repetition axis. This
produces 72 shots, each saving its own image pair at the end of ten minutes.
Saving and rearming between shots add a small amount to the total duration.
"""

from labscript import start, stop
from labscriptlib.imaq_lab.connection_table import ConnectionTable


ConnectionTable()

SHOT_DURATION = 10.0 * 60.0
IMAGE_TIME = 4.0
TRIGGER_DURATION = 1e-3

# Match the fixed exposure and gain used for the loading/decay measurements.
# Hardware triggers set the image cadence; automatic brightness changes are off.
EXPOSURE_US = 998.0
GAIN_DB = 17.897908896641724

for camera in (imaq_cam1, imaq_cam2):
    attributes = {
        **{
            name: value
            for name, value in camera.camera_attributes.items()
            if name != 'AcquisitionControl::TriggerMode'
        },
        'AnalogControl::GainAuto': 'Off',
        'AnalogControl::Gain': GAIN_DB,
        'AcquisitionControl::ExposureAuto': 'Off',
        'AcquisitionControl::ExposureMode': 'Timed',
        'AcquisitionControl::ExposureTime': EXPOSURE_US,
        'AcquisitionControl::AcquisitionFrameRateEnable': False,
    }
    attributes['AcquisitionControl::TriggerMode'] = 'On'
    camera.camera_attributes = attributes
    camera.set_property(
        'camera_attributes', attributes, 'device_properties', overwrite=True
    )
    camera.set_property('monitor_interval', SHOT_DURATION, 'device_properties')

start()

# Keep the MOT coil and both beams on at fixed values throughout each shot.
# Consecutive shots use the same values, and the MOT remains on between them.
mot_repumper_analog.constant(0.0, repump_amp_setpoint)
mot_laser_analog.constant(0.0, mot_amp_setpoint)
mot_gradient_amp.constant(0.0, mot_gradient_setpoint)
c2_AO_dummy.constant(0.0, 0.0)

# Capture early so the camera's 30 s frame timeout is never used for the
# ten-minute hold. The initial 4 s also allows the first shot's MOT to load.
imaq_cam1.expose(
    t=IMAGE_TIME,
    name='mot_long_term',
    frametype='mot_cam1',
    trigger_duration=TRIGGER_DURATION,
)
imaq_cam2.expose(
    t=IMAGE_TIME,
    name='mot_long_term',
    frametype='mot_cam2',
    trigger_duration=TRIGGER_DURATION,
)

# Hold the outputs until the next shot. The unchanged dummy sample keeps
# card 2's buffered analog acquisition well formed.
c2_AO_dummy.constant(SHOT_DURATION - 10e-3, 0.0)
stop(SHOT_DURATION)
