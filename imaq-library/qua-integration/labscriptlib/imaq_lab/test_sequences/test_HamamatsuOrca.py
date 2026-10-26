import labscript as lab
from labscriptlib.imaq_lab.connection_table import ConnectionTable
from labscript import start, stop

#TWO INDEPENDENT FRAME GRABS
# ConnectionTable()
# start()

# t = 0.0
# hamamatsu.expose(
#     t=0.100,
#     name='hamamatsu_test',
#     frametype='bright',
#     trigger_duration=10e-3,
# )

# hamamatsu.expose(
#     t=0.300,
#     name='hamamatsu_test',
#     frametype='dark',
#     trigger_duration=10e-3,
# )

# stop(0.800)



#MULTI-SHOT array of varying exposure times, written in runmanager globals
HAMAMATSU_EXPOSURE = hamamatsu_exposure

ConnectionTable()

start()
t = 0.0

hamamatsu.expose(
    t=0.500,
    name='hamamatsu_exposure_scan',
    frametype='frame',
    trigger_duration=50e-3,
)

stop(2.000)