import labscript as lab
from labscriptlib.imaq_lab.connection_table import ConnectionTable


# Load your hardware definitions
ConnectionTable()

lab.start()

# Writing a digital output and analog output "high" at a specified time, then "low" at a later time.

t = 0

t = 0.1
do8.go_low(t)
ao0.constant(t, 0)

t += 0.1
do8.go_high(t)
ao0.constant(t, 3)

t += 0.5
do8.go_low(t)
ao0.constant(t, 0)

#instead of going low at a specified time/labscript variable, we want to use a conditional stop based on a real measurement (ex. photons counted). 
t += 0.1

lab.stop(t)
