"""Image the settled MOT and its background at each laser setpoint.

Scan mot_amp_setpoint in Runmanager while keeping repump_amp_setpoint and
mot_gradient_setpoint fixed. Keep the coil on and wait MOT_SETTLE_TIME at the
new laser setting before imaging; there is no initial cloud-clearing step.
Increase MOT_SETTLE_TIME if a scan point needs longer to reach steady brightness.
The MOT and background image names remain unchanged for existing analysis.
"""

from labscript import start, stop
from labscriptlib.imaq_lab.connection_table import ConnectionTable

ConnectionTable()

BACKGROUND_CLEAR_TIME = 0.5
MOT_SETTLE_TIME = 4.0
MOT_RELOAD_TIME = 4.0

# Fix automatic gain for brightness comparisons, retaining the existing gain
# value, 1 ms exposure, ROI, and camera-specific trigger settings/delays.
for camera in (imaq_cam1, imaq_cam2):
    attributes = dict(camera.camera_attributes)
    trigger_mode = attributes.pop('AcquisitionControl::TriggerMode')
    attributes['AnalogControl::GainAuto'] = 'Off'
    attributes['AcquisitionControl::TriggerMode'] = trigger_mode
    camera.camera_attributes = attributes
    camera.set_property(
        'camera_attributes', attributes, 'device_properties', overwrite=True
    )

start()

t = 0.0

# Apply the new laser setpoint with the coil on and the repumper independent.
mot_repumper_analog.constant(t, repump_amp_setpoint)
mot_laser_analog.constant(t, mot_amp_setpoint)
mot_gradient_amp.constant(t, mot_gradient_setpoint)
c2_AO_dummy.constant(t, 0.0)

# Allow the existing cloud to settle at this shot's laser intensity.
t += MOT_SETTLE_TIME

# First pair: image the settled MOT with both cameras.
t += 10e-3
imaq_cam1.expose(
    t=t,
    name='flir_camera_images',
    frametype='mot_cam1',
    trigger_duration=1e-3,
)
imaq_cam2.expose(
    t=t,
    name='flir_camera_images',
    frametype='mot_cam2',
    trigger_duration=1e-3,
)

# Allow the first images to finish before switching off the MOT coil.
# Keep the MOT laser and repumper on for the second pair.
t += 50e-3
mot_gradient_amp.constant(t, 0.0)

# Wait for the cloud to disappear, then trigger both background images.
t += BACKGROUND_CLEAR_TIME
imaq_cam1.expose(
    t=t,
    name='flir_camera_images',
    frametype='background_cam1',
    trigger_duration=1e-3,
)
imaq_cam2.expose(
    t=t,
    name='flir_camera_images',
    frametype='background_cam2',
    trigger_duration=1e-3,
)

# Allow the approximately 1 ms exposures to finish, then restore the MOT coil.
t += 5e-3
mot_gradient_amp.constant(t, mot_gradient_setpoint)

# Wait 5s with the MOT restored before ending the shot.
# The extra AO sample also keeps buffered card 2 acquisition well formed.
c2_AO_dummy.constant(t + 10e-3, 0.0)
t += MOT_RELOAD_TIME
stop(t)
