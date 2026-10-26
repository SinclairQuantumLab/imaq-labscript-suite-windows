import labscript as lab
from labscriptlib.imaq_lab.connection_table import ConnectionTable


# Load your hardware definitions
ConnectionTable()

lab.start()

# Test PXIe-6738 AO0, pulseblaster gets following commands and sends pulses to make them happen

t = 0
value = 3
for i in range(100):
    value += 0.01
    if i%2 == 0:
        ao0.constant(t, value) 
    else:
        ao0.constant(t, 0)
    do8.go_high(t)
    t += 1e-3
    do8.go_low(t)
    t+= 1e-3

ao0.constant(t,0)
t += 0.1


lab.stop(t)
