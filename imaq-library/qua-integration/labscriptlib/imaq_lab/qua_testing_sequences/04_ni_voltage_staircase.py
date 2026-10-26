"""Lesson 4: a Python loop builds a buffered voltage staircase on NI AO30."""
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
            # This Python loop runs while compiling. The NI buffer holds the values.
            for t, volts in [(0.125, 1), (0.25, 2), (0.375, -1),
                             (0.5, -2), (0.625, 1), (2.75, 0.0)]:
                ct.c1_AO30.constant(t, volts)
        finish(playbacks)
    return program


ct.opx_main.set_qua_program_builder(build_program)
stop(3.0)
