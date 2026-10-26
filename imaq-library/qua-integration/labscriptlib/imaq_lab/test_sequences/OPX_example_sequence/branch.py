import labscript as lab
from labscriptlib.imaq_lab.connection_table import ConnectionTable


# Load your hardware definitions
ConnectionTable()

lab.start()

# Test PXIe-6738 AO0, pulseblaster gets following commands and sends pulses to make them happen

t = 0
CONDITION = False # this needs to become a qua real time variable
for i in range(2):
    t += 1e-3
    if CONDITION == True: #qua real time variable determines which branch plays
        t += 1e-3
        do8.go_high(t) # in first branch, do8 goes high and low
        t += 1e-3
        do8.go_low(t)
        t+= 1e-3
    else:
        do9.go_high(t) # in second branch, do9 goes high and low
        t += 1e-3
        do9.go_low(t)
        t+= 1e-3




ao0.constant(t,0)
t += 0.01


lab.stop(t)
