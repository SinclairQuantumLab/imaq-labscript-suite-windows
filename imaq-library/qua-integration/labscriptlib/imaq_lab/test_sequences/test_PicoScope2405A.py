from labscript import start, stop, add_time_marker
from labscriptlib.imaq_lab.connection_table import ConnectionTable


t_trigger = 0.100       # PicoScope trigger time
trigger_duration = 1e-3 # 1 ms TTL pulse to PicoScope Channel D

t_stop = 0.180

# PicoScope capture window:

pre_trigger_s = 5e-3
post_trigger_s = 60e-3


sample_rate_Hz = 200e3

ConnectionTable()

start()
t = 0.0

ao0.constant(0.000, 0.0)


# Arm PicoScope and schedule trigger

picoscope_2405a.capture(
    t=t_trigger,
    name="ao0_to_picoscope_A_test",
    channels=("A", "D"),
    sample_rate_Hz=sample_rate_Hz,
    pre_trigger_s=pre_trigger_s,
    post_trigger_s=post_trigger_s,
    voltage_range="5V",
    trigger_duration=trigger_duration,
)

# ----------------------------
# AO waveform after trigger
# ----------------------------
# These times are absolute labscript times.
# PicoScope time axis should show these relative to trigger:
#   0.105 s absolute -> +5 ms on Pico trace
#   0.115 s absolute -> +15 ms on Pico trace
#   etc.

for i in range(6):
    ao0.constant(0.105 + 0.01*i, 0.5 + 0.5*i)  # 0.5 V steps from 0.5 to 3.0 V


# Hold at 0 V before stopping
ao0.constant(0.170, 0.0)

stop(t_stop)