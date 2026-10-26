"""Offline regressions for replaying Labscript instructions in a QUA rebuild."""

import unittest

import labscript
from labscript import AnalogOut, DigitalOut, IntermediateDevice, LabscriptError
from labscript.compiler import compiler
from qm import qua

from user_devices.opx.labscript_devices import OPX


class BufferedOutputs(IntermediateDevice):
    allowed_children = (AnalogOut, DigitalOut)
    clock_limit = 100_000


class QuaRebuildTests(unittest.TestCase):
    def setUp(self):
        labscript.labscript_cleanup()
        self.addCleanup(labscript.labscript_cleanup)
        self.opx = OPX('test_opx', host='localhost', cluster_name='offline')
        device = BufferedOutputs('test_outputs', self.opx.clock_line)
        self.analog = AnalogOut('test_analog', device, 'ao0')
        self.digital = DigitalOut('test_digital', device, 'port0/line0')
        labscript.start()
        self.analog.ramp(0.325, 0.5, 0.0, 0.2, samplerate=1000)
        self.digital.go_high(0.325)
        # Match the quantised state present after pseudoclock compilation.
        self.analog.offset_instructions_from_trigger([0.0])
        self.digital.offset_instructions_from_trigger([0.0])
        self.before = self.opx._snapshot_output_state()

    def replay(self):
        with qua.program() as program:
            self.analog.ramp(0.325, 0.5, 0.0, 0.2, samplerate=1000)
            self.digital.go_low(0.325)
        return program

    def test_rebuild_accepts_quantised_ramp_and_preserves_outputs(self):
        self.opx._qua_program_builder = self.replay
        program = self.opx._run_qua_program_builder_preserving_labscript_outputs()
        self.assertIsNotNone(program)
        self.assertEqual(self.opx._snapshot_output_state(), self.before)
        self.assertFalse(compiler.suppress_all_warnings)

    def test_failed_rebuild_restores_outputs_and_warning_setting(self):
        def failing_builder():
            self.replay()
            raise RuntimeError('builder failed')

        self.opx._qua_program_builder = failing_builder
        compiler.suppress_all_warnings = True
        with self.assertRaisesRegex(RuntimeError, 'builder failed'):
            self.opx._run_qua_program_builder_preserving_labscript_outputs()
        self.assertEqual(self.opx._snapshot_output_state(), self.before)
        self.assertTrue(compiler.suppress_all_warnings)

    def test_first_pass_still_rejects_overlapping_ramps(self):
        with self.assertRaises(LabscriptError):
            self.analog.ramp(0.4, 0.1, 0.0, 0.2, samplerate=1000)


if __name__ == '__main__':
    unittest.main()
