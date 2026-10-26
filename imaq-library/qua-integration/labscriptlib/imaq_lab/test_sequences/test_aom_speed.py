import labscript as lab
from labscriptlib.imaq_lab.connection_table import ConnectionTable


ConnectionTable()

lab.start()

t = 0.0

# this sequence tests the AOM speed of the MOT and repumper AOMs. The AOM speed is measured by opening the AOM for a short time and then closing it. 
#W We care about determining the delay time, before the power starts changing, and the rise time, the time it takes to go from 10% to 90% of the final 
# value. The AOM speed is measured by opening the AOM for a short time and then closing it. The time between the open and close is varied to determine 
# the delay time and rise time.
for i in range(200):
    t += .01
    lab.add_time_marker(t, 'shutter close')
    mot_aom_analog.constant(t, 0)
    repumper_aom_analog.constant(t, 0)
    t += .01
    lab.add_time_marker(t, 'shutter open')
    mot_aom_analog.constant(t, 0.7)
    repumper_aom_analog.constant(t, 0.7)

t += 0.1

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