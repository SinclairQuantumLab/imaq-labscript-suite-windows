import labscript as lab
from labscriptlib.imaq_lab.connection_table import ConnectionTable


ConnectionTable()

lab.start()

# PXIe-6535 digital output test on port0/line0
do8.go_low(0.000)
do8.go_high(2.00)
do8.go_low(4.00)
do8.go_high(6.00)
do8.go_low(8.00)

lab.stop(10.00)