import labscript as lab
from labscriptlib.imaq_lab.connection_table import ConnectionTable


ConnectionTable()

lab.start()

t = 0.0

# this sequence tests the shutter speed of the MOT and repumper shutters. The shutter speed is measured by opening the shutter for a short time and then closing it. The time between the open and
for i in range(100):
    t += .1
    lab.add_time_marker(t, 'shutter close')
    mot_shutter_do.go_low(t)
    repumper_shutter_do.go_low(t)
    t += .1
    lab.add_time_marker(t, 'shutter open')
    mot_shutter_do.go_high(t)
    repumper_shutter_do.go_high(t)

t += 0.1

# Card 1 holds a nonzero default AO value even in this digital-only test.
# DAQmx needs at least two buffered samples; reassert the same value so the
# analog clock has another tick, without changing any analog output voltage.
c1_AO0.constant(0.0, c1_AO0.default_value)
c1_AO0.constant(t - 0.01, c1_AO0.default_value)

lab.stop(t)