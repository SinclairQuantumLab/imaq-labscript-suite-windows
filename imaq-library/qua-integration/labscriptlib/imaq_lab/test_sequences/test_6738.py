import labscript as lab
from labscriptlib.imaq_lab.connection_table import ConnectionTable


# Load your hardware definitions
ConnectionTable()

lab.start()

# Test PXIe-6738 AO0, pulseblaster gets following commands and sends pulses to make them happen
ao0.constant(0.000, 0.0)
ao0.constant(1.00, 1.0)
ao0.constant(4.50, 2.0)
ao0.constant(6.00, -1.0)
ao0.constant(8.00, 0.0)

lab.stop(10.00)

""" The full logic is:

Test file:
    ao0.constant(0.100, 1.0)

Connection table:
    ao0 is on ni_pxie_6738

Connection table:
    ni_pxie_6738 is clocked by ni_pxie_6738_clock

Connection table:
    ni_pxie_6738_clock is PulseBlaster flag 0

Compiler:
    therefore PulseBlaster flag 0 must pulse at the times needed by ao0 
    
    PXIe-6738 buffer:
    sample 0:  0.0 V
    sample 1:  1.0 V
    sample 2:  2.0 V
    sample 3: -1.0 V
    sample 4:  0.0 V

PulseBlaster flag 0 program:
    pulse at t = 0.000 s
    pulse at t = 0.100 s
    pulse at t = 0.200 s
    pulse at t = 0.300 s
    pulse at t = 0.400 s
    """