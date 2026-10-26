"""Lesson 7: a dense AO30 ramp and sparse DO00 pulses use separate NI clocks."""
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
            ct.c1_AO30.ramp(0.125, 0.5, 0.0, 0.2, samplerate=1000)
            ct.c1_AO30.constant(0.625, 0.2)
            ct.c1_AO30.constant(0.75, 0.0)
            ct.do0.go_high(0.25)
            ct.do0.go_low(0.375)
            ct.do0.go_high(0.5)
            ct.do0.go_low(0.625)
            # Scope DO7 vs DO8: dense analog updates vs a few digital changes.
        finish(playbacks)
    return program


ct.opx_main.set_qua_program_builder(build_program)
stop(1.0)
