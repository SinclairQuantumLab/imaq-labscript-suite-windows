"""Record MOT fluorescence versus time after switching on the gradient coil."""

from labscript import start, stop
from labscriptlib.imaq_lab.connection_table import ConnectionTable


ConnectionTable()

CLOUD_CLEAR_TIME = 0.5
CAPTURE_DURATION = 30.0
FRAME_RATE_HZ = 20.0
FRAME_INTERVAL = 1.0 / FRAME_RATE_HZ
TRIGGER_DURATION = 1e-3
READOUT_WAIT = 50e-3

# These are the cameras' current exposure and gain readbacks. Keep both fixed
# so automatic brightness adjustments cannot mask changes in fluorescence.
EXPOSURE_US = 998.0  # Approximately 1 ms.
GAIN_DB = 17.897908896641724  # Approximately 18 dB.

# Use synchronized pairs every 50 ms to follow the approximately 4 s loading
# curve. Configure this shot's device properties and keep the existing ROIs.
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
    # Enable triggering last, after configuring the trigger and exposure.
    attributes['AcquisitionControl::TriggerMode'] = 'On'
    camera.camera_attributes = attributes
    camera.set_property(
        'camera_attributes', attributes, 'device_properties', overwrite=True
    )
    camera.set_property('mot_on_time', CLOUD_CLEAR_TIME, 'device_properties')
    camera.set_property('frame_interval', FRAME_INTERVAL, 'device_properties')

start()

# Empty the trap while keeping its illumination fixed throughout the shot.
mot_repumper_analog.constant(0.0, repump_amp_setpoint)
mot_laser_analog.constant(0.0, mot_amp_setpoint)
mot_gradient_amp.constant(0.0, 0.0)
c2_AO_dummy.constant(0.0, 0.0)

# Begin loading and imaging together. Each image averages approximately 1 ms
# of fluorescence starting just after its hardware trigger.
mot_on_time = CLOUD_CLEAR_TIME
mot_gradient_amp.constant(mot_on_time, mot_gradient_setpoint)

number_of_frames = round(CAPTURE_DURATION * FRAME_RATE_HZ)
for frame_index in range(number_of_frames):
    t = mot_on_time + frame_index * FRAME_INTERVAL
    imaq_cam1.expose(
        t=t,
        name='mot_loading',
        frametype='mot_cam1',
        trigger_duration=TRIGGER_DURATION,
    )
    imaq_cam2.expose(
        t=t,
        name='mot_loading',
        frametype='mot_cam2',
        trigger_duration=TRIGGER_DURATION,
    )

# Repeated frametypes are saved as ordered image stacks. The EXPOSURES tables
# contain their trigger times; subtract mot_on_time to plot time since turn-on.
capture_end = mot_on_time + CAPTURE_DURATION
c2_AO_dummy.constant(capture_end, 0.0)
stop(capture_end + READOUT_WAIT)
