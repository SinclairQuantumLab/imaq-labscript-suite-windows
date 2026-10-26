"""Lesson 6: NI AO30 ramps from 0 to +0.2 V over 500 ms at 1 ksample/s."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from labscript import stop
from qm import qua
from sequence_support import setup, begin, section, finish

ct, playbacks = setup()


def build_program():
    with qua.program() as program:
        begin(ct, playbacks)
        with section(ct, playbacks):
            # Binary-fraction endpoints avoid the driver's repeated-builder rounding issue.
            ct.c1_AO30.ramp(0.125, 0.001, 0.0, 1, samplerate=100_000)
            #ct.c1_AO30.constant(0.225, 0)
        finish(playbacks)
    return program


ct.opx_main.set_qua_program_builder(build_program)
stop(1.0)
