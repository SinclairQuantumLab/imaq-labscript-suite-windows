"""Lesson 1: one OPX DO1 scope pulse; NI AO30 stays zero and DO01 stays low."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from labscript import stop
from qm import qua
from opx_configuration import SCOPE_DIGITAL
from sequence_support import setup, begin, section, wait_seconds, finish

ct, playbacks = setup()


def build_program():
    # The driver calls this twice; put only Labscript/QUA instructions here.
    with qua.program() as program:
        begin(ct, playbacks)

        with section(ct, playbacks):
            wait_seconds(0.125, SCOPE_DIGITAL)
            # QUA duration overrides use 4 ns cycles: 2,500,000 cycles = 10 ms.
            qua.play("high", SCOPE_DIGITAL, duration=2_500_000)
        finish(playbacks)
    return program


ct.opx_main.set_qua_program_builder(build_program)
stop(1.0)
