"""Lesson 9: replay two NI ramp/gate sections, first at 1x time then 2x time."""
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
        for name, t0, scale in [("normal", 0.0, 1.0), ("slower", 0.5, 2.0), ("faster", 2.0, 0.1)]:
            with section(ct, playbacks, name, t0, 0.5, time_dilation=scale):
                # Leave an initial zero hold before the ramp in each section.
                ct.c1_AO30.ramp(t0 + 0.0625, 0.25, 0.0, 0.2, samplerate=1000)
                ct.c1_AO30.constant(t0 + 0.3125, 0.2)
                ct.c1_AO30.constant(t0 + 0.375, 0.0)
                ct.do0.go_high(t0 + 0.125)
                ct.do0.go_low(t0 + 0.375)
        finish(playbacks)
    return program


ct.opx_main.set_qua_program_builder(build_program)
stop(3.0)  # Nominal time. Physical sections last 0.5 s + 1.0 s, plus completion.
