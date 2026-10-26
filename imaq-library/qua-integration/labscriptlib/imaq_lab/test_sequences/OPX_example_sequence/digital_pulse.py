'''
    This is a simple file that shows you the minimal elements you need 
    to write your own experimental sequence.
'''
import numpy as np
from labscript import (
    AnalogIn,
    AnalogOut,
    ClockLine,
    DDS,
    DigitalOut,
    MHz,
    Shutter,
    StaticDDS,
    WaitMonitor,
    start,
    stop,
    wait,
)
from labscriptlib.imaq_lab.connection_table import ConnectionTable


ConnectionTable()

# Begin issuing labscript primitives.
# Start() elicits the commencement of the shot.
start()

dt = 1e-3

t = 0
for i in range(100):
    t += 1
    demo_do.go_low(t)
    t += dt
    demo_do.go_high(t)
    t += dt
    i+=1

t += dt

stop(t=t)