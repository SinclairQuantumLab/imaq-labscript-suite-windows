import numpy
import PySpin
from IPython.display import Image, display
from pathlib import Path
import matplotlib.pyplot as plt
from labscript import start, stop

from labscriptlib.imaq_lab.connection_table import ConnectionTable

ConnectionTable()

start()

t=0
t += 0.5
imaq_cam1.expose(
    t=0.500,
    name = 'flir_camera__test',
    frametype = 'frame1cam1',
    trigger_duration=50e-3,
)

imaq_cam2.expose(
    t=0.500,
    name = 'flir_camera__test',
    frametype = 'frame1cam2',
    trigger_duration=50e-3,
)

t += 0.5
imaq_cam1.expose(
    t=1.000,
    name = 'flir_camera__test',
    frametype = 'frame2cam1',
    trigger_duration=50e-3,
)

imaq_cam2.expose(
    t=1.000,
    name = 'flir_camera__test',
    frametype = 'frame2cam2',
    trigger_duration=50e-3,
)

t+=1

stop(t)