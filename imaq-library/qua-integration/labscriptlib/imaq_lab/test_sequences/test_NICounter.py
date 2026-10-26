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
dt = 5e-3
num_steps = 10
spcm_buffer_time = 100e-6
ao0.constant(t, 0.0)
ao1.constant(t, 0.0)
do8.go_high(t)

t += 1e-3

# Acquire AI0 while AO0 is outputting voltages.
ai0.acquire('ai0_trace', start_time=t, end_time= t + dt*num_steps)



# configure the counting stuff now
step_time = dt
start_times = t + np.arange(0, num_steps, 1) * step_time

# Trigger the counting card
spcm_start = lambda t: t + spcm_buffer_time
spcm_end = lambda t: t + step_time - spcm_buffer_time
spcm_trigger_times = [f(t) for t in start_times for f in (spcm_start, spcm_end)]

ni_pxi_6602_counter0.acquire(t, spcm_trigger_times)
print(f"spcm_counter.acquire() successful")

for i in range(num_steps):
    ao0.constant(t,0.1*i)
    ao1.constant(t, 0.1*i)
    do9.go_high(t+dt/10)
    do9.go_low(t+dt/4)
    do9.go_high(t+dt/2)
    do9.go_low(t+3*dt/4)
    t += dt


ao0.constant(t,0)
ao1.constant(t,0)
do8.go_low(t)

t += 1e-3

stop(t)