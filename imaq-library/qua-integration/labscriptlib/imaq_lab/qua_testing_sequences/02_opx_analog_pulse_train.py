"""Lesson 2: a QUA for-loop sends five +0.1 V, 100 us pulses to OPX AO3."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from labscript import stop
from qm import qua
from opx_configuration import SCOPE_ANALOG
from sequence_support import setup, begin, section, wait_seconds, finish

ct, playbacks = setup()


def build_program():
    with qua.program() as program:
        begin(ct, playbacks)
        with section(ct, playbacks):
            wait_seconds(0.125, SCOPE_ANALOG)
            pulse = qua.declare(int)
            with qua.for_(pulse, 0, pulse < 5, pulse + 1):
                qua.play("pulse", SCOPE_ANALOG)  # Pulse width set in opx_configuration.
                wait_seconds(0.0099, SCOPE_ANALOG)  # 100 us + 9.9 ms = 10 ms period.
        finish(playbacks)
    return program


ct.opx_main.set_qua_program_builder(build_program)
stop(1.0)
