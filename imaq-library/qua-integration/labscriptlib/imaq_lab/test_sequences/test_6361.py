# from labscript import start, stop, add_time_marker
# from labscriptlib.imaq_lab.connection_table import ConnectionTable

# ConnectionTable()

# start()

# # Start AO0 at 0 V before acquisition.
# ao0.constant(0.000, 0.0)
# ao1.constant(0.000, 0.0)

# # Acquisition window.
# t_acq_start = 0.020
# t_acq_stop = 0.220

# # Trigger PXIe-6361 AI acquisition.
# add_time_marker(t_acq_start, 'Start AI acquisition')
# ai_start_trigger_tick.go_high(t_acq_start)
# ai_start_trigger_tick.go_low(t_acq_start + 0.001)

# # Acquire AI0/AI1 while AO0 changes.
# ai0.acquire('ai0_trace', start_time=t_acq_start, end_time=t_acq_stop)
# ai1.acquire('ai1_trace', start_time=t_acq_start, end_time=t_acq_stop)

# # AO0 steps during the acquisition window.
# ao0.constant(0.080, 2.5)
# ao0.constant(0.150, 0.0)

# stop(0.240)

#////////////////
#ABOVE: STEP TEST
#BELOW: SINE TEST
#////////////////

import numpy as np

from labscript import start, stop, add_time_marker
from labscriptlib.imaq_lab.connection_table import ConnectionTable

ConnectionTable()

start()
t = 0.0
ni_pxie_6361_acquisition_trigger.go_high(t)
t += 1e-3
ni_pxie_6361_acquisition_trigger.go_low(t)


# Initial values before acquisition
c1_AO0.constant(t, 0.0)
c1_AO1.constant(t, 0.0)
do8.go_high(t)

t += 1e-3

# Acquire AI0 while AO0 is outputting voltages.
ai0.acquire('ai0_trace', start_time=t, end_time= t + 5e-3)

for i in range(10):
    c1_AO0.constant(t,0.1*i)
    c1_AO1.constant(t, 0.1*i)
    t += 0.5e-3


c1_AO0.constant(t,0)
c1_AO1.constant(t,0)
do8.go_low(t)

t += 1e-3

do8.go_low(t - 0.5e-3) 

stop(t)