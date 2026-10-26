"""One simultaneous MOT/repumper closing test with a scope reference.

Scope CH1: photodiode after the beam(s) being measured.
Scope CH2: do21 (PXI1Slot6 port2/line5).
Trigger the scope on the FALLING edge of do21, with some pre-trigger data.

Both shutters are commanded OPEN and both AOMs set to 0.7 V at the start.
At t = 50 ms, close_shuttered_beam() commands both AOMs OFF and do21 falls.
The photodiode should fall shortly afterward, allowing for physical response.
The helper commands the shutters CLOSED after its AOM guard time, then
restores 0.7 V behind the closed shutters after its closing delay/headroom.
The photodiode should remain LOW during that restore and the following
50 ms observation interval. This checks the closing helper's full sequence.

No Runmanager globals are required. Finally, both AOMs return to 0 V,
both shutters remain CLOSED, and do21 remains LOW.
"""

# Device names become available when ConnectionTable() is called.
# pylint: disable=undefined-variable
# pyright: reportUndefinedVariable=false

import labscript as lab
from labscriptlib.imaq_lab.connection_table import ConnectionTable
from labscriptlib.imaq_lab.sequence_utils import close_shuttered_beam


CLOSE_TIME = 50e-3
AOM_ON_VOLTAGE = 0.7
CLOSED_OBSERVATION_TIME = 50e-3
FINAL_DARK_TIME = 20e-3


def main():
    ConnectionTable()
    lab.start()
    beams = (
        (mot_shutter_do, mot_aom_analog),
        (repumper_shutter_do, repumper_aom_analog),
    )

    # Allow the shutters to open and the light to settle before closing.
    do21.go_high(0.0)
    for shutter, aom in beams:
        shutter.go_high(0.0)
        aom.constant(0.0, AOM_ON_VOLTAGE)
    lab.add_time_marker(0.0, 'Both shutters OPEN, both AOMs ON, do21 HIGH')

    t = CLOSE_TIME
    restore_times = []
    for shutter, aom in beams:
        restore_times.append(
            close_shuttered_beam(t, AOM_ON_VOLTAGE, shutter, aom)
        )
    do21.go_low(t)
    lab.add_time_marker(t, 'Both AOMs OFF + do21 falling edge')

    # The helper returns the time at which it restores the AOM voltage.
    restore_time = max(restore_times)
    lab.add_time_marker(
        restore_time, 'AOMs restored behind CLOSED shutters: light stays dark',
    )

    cleanup_time = restore_time + CLOSED_OBSERVATION_TIME
    for _, aom in beams:
        aom.constant(cleanup_time, 0.0)
    # The digital card needs at least four buffered samples. Reassert LOW
    # to add a clock tick while keeping do21 and both shutters unchanged.
    do21.go_low(cleanup_time)
    lab.add_time_marker(cleanup_time, 'End observation: both AOMs return to 0 V')
    lab.stop(cleanup_time + FINAL_DARK_TIME)
    print(
        f'Both AOMs OFF and do21 falling edge at {t:.6f} s; '
        f'AOM voltage restored behind closed shutters at {restore_time:.6f} s'
    )


if __name__ == "__main__":
    main()
