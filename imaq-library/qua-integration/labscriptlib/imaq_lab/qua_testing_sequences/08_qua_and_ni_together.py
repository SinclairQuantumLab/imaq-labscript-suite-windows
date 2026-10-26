"""Lesson 8: OPX DO1/AO3 pulses overlap an NI AO30 ramp and DO01 gate."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from labscript import stop
from qm import qua
from opx_configuration import SCOPE_ANALOG, SCOPE_DIGITAL
from sequence_support import setup, begin, section, wait_seconds, finish

ct, playbacks = setup()


def build_program():
    with qua.program() as program:
        begin(ct, playbacks)
        gain = qua.declare(qua.fixed, value=-1)

        with section(ct, playbacks):
            ct.c1_AO30.ramp(0.125, 0.5, 0.0, 0.2, samplerate=1000)
            ct.c1_AO30.constant(0.625, 0.2)
            ct.c1_AO30.constant(0.75, 0.0)
            ct.do0.go_high(0.125)
            ct.do0.go_low(0.25)
            ct.do0.go_high(0.325)
            ct.do0.go_low(0.625)
            wait_seconds(0.125, SCOPE_ANALOG)
            wait_seconds(0.125, SCOPE_DIGITAL)
            pulse = qua.declare(int)
            with qua.for_(pulse, 0, pulse < 100, pulse + 1):
                #Range is [0,1] for amplitude modification.
                # Independent element timelines advance concurrently.
                qua.play("pulse" * qua.amp(gain), SCOPE_ANALOG)
                qua.assign(gain, gain + 0.02)
                qua.play("high", SCOPE_DIGITAL)
                wait_seconds(0.0099, SCOPE_ANALOG)
                wait_seconds(0.0099, SCOPE_DIGITAL)
        finish(playbacks)
    return program


ct.opx_main.set_qua_program_builder(build_program)
stop(1.0)
