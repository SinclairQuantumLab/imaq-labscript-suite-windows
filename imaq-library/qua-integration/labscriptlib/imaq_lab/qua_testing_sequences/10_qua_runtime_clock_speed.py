"""Lesson 10: a QUA conditional chooses 0.5x or 2x time for both NI clocks."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from labscript import stop
from qm import qua
from user_devices.opx.tick_playback_types import TimeDilationPolicy
from sequence_support import (
    setup, begin, section, finish, wait_runtime_seconds,
)

# Set to 0 and recompile to select the faster branch. This is an instructional
# QUA variable, not measurement feedback; it does not require an analog input.
BRANCH = 0
ct, playbacks = setup()


def build_program():
    with qua.program() as program:
        begin(ct, playbacks)
        choice = qua.declare(int, value=BRANCH)
        scale = qua.declare(qua.fixed)
        with qua.if_(choice > 0):
            qua.assign(scale, 2.0)
        with qua.elif_(choice == 0):
            qua.assign(scale, 1)
        with qua.else_():
            qua.assign(scale, 0.25)
        with section(
            ct, playbacks,
            time_dilation_policy=TimeDilationPolicy.qua_logic,
            qua_var_time_dilation=scale,
        ):
            # NI sample values stay fixed; the QUA branch changes their edge spacing.
            ct.c1_AO30.ramp(0.125, 0.5, 0.0, 0.2, samplerate=1000)
            ct.c1_AO30.constant(0.625, 0.2)
            ct.c1_AO30.constant(0.75, 0.0)
            ct.c2_AO0.ramp(0.125, .125, 0.0, 1, samplerate=1000)
            ct.c2_AO0.constant(0.625, 0.2)
            ct.c2_AO0.constant(0.75, 0.0)
            ct.do0.go_high(0.125)
            ct.do0.go_low(0.25)
            ct.do0.go_high(0.325)
            ct.do0.go_low(0.425)

            # qua_logic sections have no automatic duration padding. Wait on the
            # driver's separate timing element so the final zero/low hold scales too.
            wait_runtime_seconds(1.0, scale)
        finish(playbacks)
    return program


ct.opx_main.set_qua_program_builder(build_program)
stop(1.0)  # Physical duration is about 2 s (or 0.5 s), plus the completion guard.
