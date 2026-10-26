"""Regressions for the OPX1000's observed 24-bit variable-wait duration."""
import ast
import unittest

from qm import qua
from user_devices.opx.qua_program_print import format_qua_program
from user_devices.opx.tick_playback_types import TickSegment
from user_devices.opx.tick_segment_compile import (
    emit_segment_tick_qua,
    qua_wait_scaled_cycles,
)


class RuntimeWaitBoundsTests(unittest.TestCase):
    def assert_runtime_waits_bounded(self, program):
        tree = ast.parse(format_qua_program(program))
        bases = [node.args[0].value for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "mul_int_by_fixed"]
        self.assertTrue(bases)
        # QUA fixed scales are less than 8; include the endpoint conservatively.
        self.assertTrue(all(base * 8 < (1 << 24) for base in bases), bases)

    def test_loading_scan_waits_bound_scaled_duration(self):
        for seconds in (0.2, 1.0, 5.0, 10.0):
            with self.subTest(seconds=seconds):
                with qua.program() as program:
                    scale = qua.declare(qua.fixed)
                    wait = qua.declare(int)
                    qua_wait_scaled_cycles(round(seconds / 4e-9), scale, "clock", wait)
                self.assert_runtime_waits_bounded(program)

    def test_repeated_tick_interval_uses_same_variable_wait_limit(self):
        # 12 ms * a runtime scale near 8 exceeds the 24-bit wait boundary.
        with qua.program() as program:
            scale = qua.declare(qua.fixed)
            emit_segment_tick_qua(
                [TickSegment(start_s=0, reps=10, step_cycles=3_000_000)],
                tick_element="clock", tick_operation="tick", tick_pulse_cycles=250,
                time_dilation=scale,
            )
        self.assert_runtime_waits_bounded(program)

    def test_literal_wait_path_keeps_large_constant(self):
        with qua.program() as program:
            wait = qua.declare(int)
            qua_wait_scaled_cycles(33_554_431, 1.0, "clock", wait)
        tree = ast.parse(format_qua_program(program))
        waits = [node.args[0].value for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id == "wait"]
        self.assertEqual(waits, [33_554_431])


if __name__ == "__main__":
    unittest.main()
