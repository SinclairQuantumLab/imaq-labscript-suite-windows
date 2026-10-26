"""Scan a 1 ms MOT/repumper pulse past fixed camera triggers.

Runmanager: select this shot and load MOT_light_pulse_timing_scan.h5 alongside
the usual fixed experiment globals. Enable MOT_light_pulse_timing_scan and
disable other scan/repetition groups, including MOT_monitor_repeats. The
initial light_pulse_offset_ms values are -3, -2, -1, 0, +1, +2, +3: seven full
shots, each acquiring ONE image from each camera. Edit that global's array to
change the offsets. Negative offsets put the light pulse earlier.

Repumper gating: mot_repumper_do HIGH blocks the beam; LOW enables it.
Hold mot_repumper_analog at repump_amp_setpoint throughout and use this
digital gate to create the pulse. The MOT beam is pulsed with mot_laser_analog.

Timing reference: pulse START relative to the programmed rising-edge camera
trigger. The current connection table uses PB flags 8/9, Line3, FrameStart,
RisingEdge, and Timed ExposureTime=1000 us for both cameras. It does not set
TriggerDelay. Leave each camera's attributes and existing trigger delay alone;
a trigger is NOT a measurement of actual exposure start. Camera-specific
trigger delay, internal sensor timing, and beam switching response can shift
the observed overlap. Inspect the actual attributes saved under images/<camera>
in completed shots; nominal trigger timing alone cannot establish exposure.

Images are saved under images/<camera>/mot_light_pulse_timing/ with signed
offset and camera labels. The Runmanager shot filename/run number identifies
the shot, and the globals attribute light_pulse_offset_ms records its offset. Diagnostic
times are also saved in each camera's device properties. No camera settings
are overridden, including the programmed 1 ms exposure.
"""

import math

from labscript import add_time_marker, start, stop
from labscriptlib.imaq_lab.connection_table import ConnectionTable


ConnectionTable()

# All preparation, trigger, dark-window, and restoration times are fixed.
MOT_LOAD_TIME = 4.0
DARK_LEAD_TIME = 10e-3
DARK_TAIL_TIME = 10e-3
CAMERA_TRIGGER_TIME = MOT_LOAD_TIME + DARK_LEAD_TIME
TRIGGER_DURATION = 1e-3
LIGHT_PULSE_DURATION = 1e-3
DARK_START = MOT_LOAD_TIME
DARK_END = CAMERA_TRIGGER_TIME + DARK_TAIL_TIME
MOT_RESTORE_TIME = 4.0
SHOT_END = DARK_END + MOT_RESTORE_TIME

# ONLY these two output-transition times move when Runmanager scans the offset.
offset_ms = float(light_pulse_offset_ms)
if not math.isfinite(offset_ms):
    raise ValueError('light_pulse_offset_ms must be finite.')
LIGHT_PULSE_START = CAMERA_TRIGGER_TIME + offset_ms * 1e-3
LIGHT_PULSE_END = LIGHT_PULSE_START + LIGHT_PULSE_DURATION
if not (DARK_START < LIGHT_PULSE_START and LIGHT_PULSE_END < DARK_END):
    raise ValueError(
        'The light pulse must fit strictly inside the fixed dark interval. '
        'Enlarge DARK_LEAD_TIME/DARK_TAIL_TIME for a wider offset scan.'
    )

offset_label = f'{offset_ms:+g}ms'
for camera in (imaq_cam1, imaq_cam2):
    # Check the required exposure without modifying any camera attributes.
    exposure_us = float(camera.camera_attributes['AcquisitionControl::ExposureTime'])
    if not math.isclose(exposure_us, 1000.0, rel_tol=0.0, abs_tol=1e-6):
        raise ValueError(f'{camera.name}: this test requires a programmed 1 ms exposure.')
    for key, value in {
        'light_pulse_offset_ms': offset_ms,
        'light_pulse_start_s': LIGHT_PULSE_START,
        'light_pulse_end_s': LIGHT_PULSE_END,
        'light_pulse_duration_s': LIGHT_PULSE_DURATION,
        'programmed_trigger_time_s': CAMERA_TRIGGER_TIME,
        'diagnostic_dark_start_s': DARK_START,
        'diagnostic_dark_end_s': DARK_END,
        'timing_reference': 'Light pulse start minus programmed rising-edge trigger; '
                            'actual exposure start is not assumed.',
    }.items():
        camera.set_property(key, value, 'device_properties')

start()

# Load at the normal setpoints. The coil remains on throughout the shot.
mot_repumper_analog.constant(0.0, repump_amp_setpoint)
mot_repumper_do.go_low(0.0)
mot_laser_analog.constant(0.0, mot_amp_setpoint)
mot_gradient_amp.constant(0.0, mot_gradient_setpoint)
c2_AO_dummy.constant(0.0, 0.0)

# Within this fixed interval both beams are off except for the test pulse.
add_time_marker(DARK_START, 'Diagnostic light off')
mot_repumper_do.go_high(DARK_START)
mot_laser_analog.constant(DARK_START, 0.0)

add_time_marker(LIGHT_PULSE_START, f'1 ms light pulse, offset {offset_label}')
mot_repumper_do.go_low(LIGHT_PULSE_START)
mot_laser_analog.constant(LIGHT_PULSE_START, mot_amp_setpoint)
mot_repumper_do.go_high(LIGHT_PULSE_END)
mot_laser_analog.constant(LIGHT_PULSE_END, 0.0)

add_time_marker(CAMERA_TRIGGER_TIME, 'Fixed camera trigger reference')
for camera in (imaq_cam1, imaq_cam2):
    camera.expose(
        t=CAMERA_TRIGGER_TIME,
        name='mot_light_pulse_timing',
        frametype=f'{camera.name}_offset_{offset_label}',
        trigger_duration=TRIGGER_DURATION,
    )

# Restore normal illumination at the SAME time for every offset, then reload.
add_time_marker(DARK_END, 'Restore MOT light')
mot_repumper_do.go_low(DARK_END)
mot_laser_analog.constant(DARK_END, mot_amp_setpoint)

# Keep the buffered analog output acquisition well formed, as in other shots.
c2_AO_dummy.constant(SHOT_END - 10e-3, 0.0)
stop(SHOT_END)
