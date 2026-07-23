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

if __name__ == '__main__':

    ConnectionTable()

    # Begin issuing labscript primitives.
    # Start() elicits the commencement of the shot.
    dt = 1e-4
    start()
    t = 0
    for i in range(100):
        t += dt
        do11.go_high(t)
        t += dt
        do11.go_low(t)
        t += dt
    
    stop(t=t)