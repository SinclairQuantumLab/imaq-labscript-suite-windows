"""Lesson 3: NI AO30 steps to +0.1 V at 250 ms and returns to zero at 750 ms."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from labscript import stop
from qm import qua
from sequence_support import setup, begin, section, finish

ct, playbacks = setup()
start_time = .02
duration = 0.005

def build_program():
    with qua.program() as program:
        begin(ct, playbacks)
        with section(ct, playbacks):
            # Labscript compiles these values; QUA emits their sample clocks on DO7.
            ct.c1_AO30.constant(start_time, 1)
            ct.c1_AO30.constant(start_time+duration, 0.0)
        finish(playbacks)
    return program


ct.opx_main.set_qua_program_builder(build_program)
stop(1)
