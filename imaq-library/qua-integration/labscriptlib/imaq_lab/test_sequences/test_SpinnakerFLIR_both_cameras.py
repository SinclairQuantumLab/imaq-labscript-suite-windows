import labscript as lab
import math
from labscriptlib.imaq_lab.connection_table import ConnectionTable


def main():
    ConnectionTable()


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

    lab.start()
    t = 0.0

    # uSE FOR TESTING CAMERA TIMING 
    mot_aom_analog.constant(t, 0)
    repumper_aom_analog.constant(t, 0)



    # Trigger both Spinnaker cameras simultaneously at t = 0.5 s
    t += 0.5

    # We are testing timing of camera exposure. We can scan image_wait_time and see when the camera exposure lines up with the mot_aom being on.
    mot_aom_analog.constant(t, mot_amp_setpoint)
    mot_aom_analog.constant(t + 1e-3, 0)
    repumper_aom_analog.constant(t, mot_amp_setpoint)
    repumper_aom_analog.constant(t + 1e-3, 0)

    t += image_wait_time


    imaq_cam1.expose(
        t=t,
        name='flir_camera_images',
        frametype='cam1_signal',
        trigger_duration=2e-3,
    )

    imaq_cam2.expose(
        t=t,
        name='flir_camera_images',
        frametype='cam2_signal',
        trigger_duration=2e-3,
    )

    # Leave enough time for the acquisitions to complete
    t += 0.1

    imaq_cam1.expose(
            t=t,
            name='flir_camera_images',
            frametype='cam1_background',
            trigger_duration=2e-3,
        )
    
    imaq_cam2.expose(
        t=t,
        name='flir_camera_images',
        frametype='cam2_background',
        trigger_duration=2e-3,
    )

    
    # Card 1 holds a nonzero default AO value even in this digital-only test.
    # DAQmx needs at least two buffered samples; reassert the same value so the
    # analog clock has another tick, without changing any analog output voltage.
    c1_AO0.constant(t, c1_AO0.default_value)
    do1.go_high(t)
    do2.go_high(t)
    t+=0.1
    do1.go_low(t)
    do2.go_low(t)
    c1_AO0.constant(t, c1_AO0.default_value)
    t+=0.1
    do1.go_low(t)
    do2.go_low(t)
    t += 0.1
    lab.stop(t)
    print("Sequence ends at t=%1.5f" % t)


if __name__ == "__main__":
    main()
