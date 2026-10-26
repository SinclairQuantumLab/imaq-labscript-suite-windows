"""Lesson 5: NI DO0 (port0/line1, 'do0') emits three increasing pulse widths."""
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
            # OPX DO8 clocks the 6535; these pulses appear on the NI card's DO01.
            for t, width in [(0.02, 0.03125), (0.25, 0.0625), (0.5, 0.125)]:
                ct.do0.go_high(t)
                ct.do0.go_low(t + width)
        finish(playbacks)
    return program


ct.opx_main.set_qua_program_builder(build_program)
stop(1.0)
