"""One simultaneous MOT/repumper opening pulse with a scope reference.

Scope CH1: photodiode after the beam(s) being measured.
Scope CH2: do21 (PXI1Slot6 port2/line5).
Trigger the scope on the RISING edge of do21.

Both beams start OFF with their shutters CLOSED. At 20 ms, both AOMs are
set to 0.7 V behind the closed shutters, matching the earlier opening test.
open_shuttered_beam() then turns the AOMs OFF briefly and opens the shutters
in advance. At t = 50 ms it commands both AOMs ON, together with do21 HIGH.
The photodiode should rise shortly afterward, allowing for physical response.
Both AOMs and do21 turn OFF at 100 ms; the shutters close 20 us later.

No Runmanager globals are required. Both beams finish OFF, both shutters
CLOSED, and do21 LOW. This test only calls the opening helper.
"""

# Device names become available when ConnectionTable() is called.
# pylint: disable=undefined-variable
# pyright: reportUndefinedVariable=false

import labscript as lab
from labscriptlib.imaq_lab.connection_table import ConnectionTable
from labscriptlib.imaq_lab.sequence_utils import open_shuttered_beam


OPEN_TIME = 50e-3
PULSE_DURATION = 50e-3
AOM_ON_VOLTAGE = 0.7
WARMUP_TIME = 20e-3
AOM_GUARD_TIME = 20e-6
FINAL_DARK_TIME = 50e-3


def main():
    ConnectionTable()
    lab.start()
    beams = (
        (mot_shutter_do, mot_aom_analog),
        (repumper_shutter_do, repumper_aom_analog),
    )

    do21.go_low(0.0)
    for shutter, aom in beams:
        aom.constant(0.0, 0.0)
        shutter.go_low(0.0)
        # Establish the same powered-but-blocked starting state as before.
        aom.constant(WARMUP_TIME, AOM_ON_VOLTAGE)
    lab.add_time_marker(0.0, 'Initialize: both beams dark, do21 LOW')

    t = OPEN_TIME
    for shutter, aom in beams:
        open_shuttered_beam(t, AOM_ON_VOLTAGE, shutter, aom)
    do21.go_high(t)
    lab.add_time_marker(t, 'Both AOMs ON + do21 rising edge')

    off_time = t + PULSE_DURATION
    for shutter, aom in beams:
        aom.constant(off_time, 0.0)
        shutter.go_low(off_time + AOM_GUARD_TIME)
    do21.go_low(off_time)
    lab.add_time_marker(off_time, 'Both AOMs OFF + do21 LOW')

    lab.stop(off_time + AOM_GUARD_TIME + FINAL_DARK_TIME)
    print(
        f'One simultaneous MOT/repumper opening pulse: '
        f'ON/do21 rising edge at {t:.6f} s, OFF at {off_time:.6f} s'
    )


if __name__ == "__main__":
    main()
