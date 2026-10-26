"""Compile lessons offline and inspect their real HDF5/QUA payloads.

Run with the Labscript Python environment. This never arms NI or opens a QM.
The output directory contains inspection shots, not automatically queued shots.
"""

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parent


def check_worker_buffers(ao, do):
    """Exercise the installed NI worker with a fake Task; never create a real task.

    The fake enforces the generic two-sample finite-timing minimum and the
    observed PXIe-6535 requirement of four written samples at StartTask().
    These are software regression checks based on the reported hardware errors,
    not a replacement for device validation. Real worker methods still decide
    which rows to drop and whether the nonzero defaults require a buffered task.
    """
    from types import SimpleNamespace
    from unittest.mock import patch
    from labscript_devices.NI_DAQmx import blacs_workers as ni_workers

    class OfflineTask:
        def __init__(self):
            self.samples = None
            self.written = None
            self.kind = None

        def CreateDOChan(self, *args):
            self.kind = "digital"

        def CreateAOVoltageChan(self, *args):
            self.kind = "analog"

        def CfgSampClkTiming(self, terminal, rate, edge, mode, samples):
            assert samples >= 2, (
                f"Finite NI buffer has {samples} sample(s) after the worker "
                "removes the terminal row; DAQmx requires at least 2"
            )
            self.samples = samples

        def _write(self, samples, auto_start, timeout, layout, data, written, reserved):
            assert len(data) == samples
            if self.samples is not None:
                assert samples == self.samples
            self.written = samples

        WriteDigitalU32 = _write
        WriteAnalogF64 = _write

        def StartTask(self):
            if self.samples is not None and self.kind == "digital":
                assert self.written is not None and self.written >= 4, (
                    f"PXIe-6535 initial transfer has {self.written} samples; "
                    "StartTask requires at least 4 (reported DAQmx error -200294)"
                )

    worker = SimpleNamespace(
        MAX_name="offline_validation", clock_terminal="/offline/PFI0",
        clock_limit=100e3, static_AO=False, static_DO=False,
        Vmin=-10.0, Vmax=10.0,
        ports={port: {"num_lines": 8} for port in do.dtype.names},
    )
    with patch.object(ni_workers, "Task", OfflineTask):
        ni_workers.NI_DAQmxOutputWorker.program_buffered_DO(worker, do)
        ni_workers.NI_DAQmxOutputWorker.program_buffered_AO(worker, ao)
    assert worker.DO_task.written == worker.DO_task.samples == len(do) - 1
    assert worker.AO_task.written == worker.AO_task.samples == len(ao) - 1
    return {"analog": worker.AO_task.samples, "digital": worker.DO_task.samples}


def compile_file(source, destination, connection_table):
    script = r'''
import sys
sys.excepthook = sys.__excepthook__
from qm import QuantumMachinesManager
def no_hardware(*args, **kwargs):
    raise RuntimeError("Offline validation must not connect to OPX hardware")
QuantumMachinesManager.__init__ = no_hardware
QuantumMachinesManager.open_qm = no_hardware
QuantumMachinesManager.simulate = no_hardware
import importlib.util
from labscript import labscript_init
source, destination = sys.argv[1:]
labscript_init(destination, labscript_file=source, new=True,
               overwrite=True, load_globals_values=False)
spec = importlib.util.spec_from_file_location('__main__', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
'''
    env = dict(os.environ)
    env["QUA_TESTING_CONNECTION_TABLE"] = str(connection_table)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-c", script, str(source), str(destination)],
        env=env, capture_output=True, text=True, timeout=90,
    )
    if proc.returncode:
        raise RuntimeError(proc.stdout + "\n" + proc.stderr)


def inspect_shot(path, table_path):
    import labscript_utils.h5_lock  # Must precede h5py.
    import h5py
    import numpy as np
    from labscript_utils.connections import ConnectionTable
    from qm import QuantumMachinesManager, generate_qua_script
    from user_devices.opx.opx_shot_loader import OpxShotLoader
    from user_devices.opx.shot_stream_metadata import read_execution_mode

    reference = ConnectionTable(str(table_path))
    actual = ConnectionTable(str(path))
    # Both directions confirm the lessons add/remove no connection-table channels.
    reference.assert_superset(actual)
    actual.assert_superset(reference)
    with h5py.File(path, "r") as shot:
        opx = shot["devices/opx_main"]
        assert read_execution_mode(opx) == "execute"
        assert bool(opx.attrs["is_master_pseudoclock"])
        config = OpxShotLoader.read_qua_config(opx["qua_config"])
        program = OpxShotLoader.load_stored_program(opx["qua_program"])
        QuantumMachinesManager.set_capabilities_offline(frozenset())
        source = generate_qua_script(program, config)
        syntax = ast.parse(source)
        calls = [node for node in ast.walk(syntax) if isinstance(node, ast.Call)]

        def plays(operation, element, duration=None):
            return [call for call in calls
                    if isinstance(call.func, ast.Name) and call.func.id == "play"
                    and len(call.args) >= 2
                    and isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[1], ast.Constant)
                    and call.args[0].value == operation and call.args[1].value == element
                    and (duration is None or any(
                        kw.arg == "duration" and isinstance(kw.value, ast.Constant)
                        and kw.value.value == duration for kw in call.keywords))]
        path.with_suffix(".qua.py").write_text(source, encoding="utf-8")

        fem = config["controllers"]["con1"]["fems"][3]
        assert fem["type"] == "LF"
        assert set(fem["digital_outputs"]) == {1, 7, 8}
        assert set(fem["analog_outputs"]) == {1, 3}
        for element, output in [("ni_analog_clock", 7), ("ni_digital_clock", 8),
                                ("scope_digital", 1)]:
            port = config["elements"][element]["digitalInputs"]["marker"]["port"]
            assert tuple(port) == ("con1", 3, output)
        assert tuple(config["elements"]["scope_analog"]["singleInput"]["port"]) == (
            "con1", 3, 3,
        )

        specs = OpxShotLoader.read_tick_playback_specs(opx)
        assert {s.clock_line_name for s in specs} == {
            "ni_pxie_6738_1_clock", "ni_pxie_6535_clock",
        }
        clock_rows = {}
        for spec in specs:
            ticks = np.asarray(spec.tick_cycles)
            assert ticks[0] == 0 and np.all(np.diff(ticks) > 0)
            assert spec.tick_pulse_cycles == 250
            assert sum(s.reps for plan in spec.section_tick_plans.values()
                       for s in plan) == len(ticks) - 1
            label = "analog" if spec.tick_element == "ni_analog_clock" else "digital"
            # Read syntax rather than strings: QM's serializer can include the
            # original protobuf as a diagnostic comment, repeating handle names.
            saved = [call.func.value.id for call in calls
                     if isinstance(call.func, ast.Attribute) and call.func.attr == "save_all"
                     and isinstance(call.func.value, ast.Name) and call.args
                     and isinstance(call.args[0], ast.Constant)
                     and call.args[0].value == f"learning_{label}_completion_times"]
            assert len(saved) == 1
            assert len([call for call in plays("tick", spec.tick_element)
                        if any(kw.arg == "timestamp_stream"
                               and isinstance(kw.value, ast.Name)
                               and kw.value.id == saved[0] for kw in call.keywords)]) == 1
            clock_rows[spec.clock_line_name] = len(ticks)

        ao = shot["devices/ni_pxie_6738_1/AO"][:]
        do = shot["devices/ni_pxie_6535/DO"][:]
        worker_samples = check_worker_buffers(ao, do)
        assert len(ao) == clock_rows["ni_pxie_6738_1_clock"]
        assert len(do) == clock_rows["ni_pxie_6535_clock"]
        values = ao["ao30"]
        assert np.all(np.isfinite(values)) and np.max(np.abs(values)) <= 0.201
        assert values[0] == 0.0 and values[-1] == values[-2] == 0.0, (
            "AO30 initial/final samples", values[0], values[-2:],
        )
        # Preserve the real table's other AO defaults, including the coil/AOM values.
        defaults = {"ao16": 0.7, "ao20": 2.15}
        for channel in ao.dtype.names:
            if channel != "ao30":
                np.testing.assert_allclose(ao[channel], defaults.get(channel, 0.0))
        # Only bit 1 of port0 may change. Shutter defaults on port2 are both high.
        expected_ports = {"port0": 0, "port1": 0, "port2": 192}
        for port in do.dtype.names:
            data = do[port].astype(np.uint64)
            if port == "port0":
                assert np.all((data & np.uint64(0xFFFFFFFD)) == 0)
                assert data[0] == 0 and data[-1] == data[-2] == 0
            else:
                assert np.all(data == expected_ports[port])

        number = int(path.name[:2])
        if number <= 2:
            assert np.all(values == 0) and np.all(do["port0"] == 0)
        if number == 1:
            assert plays("high", "scope_digital", duration=2_500_000)
        if number == 2:
            assert plays("pulse", "scope_analog") and "for_(" in source
        if number == 3:
            np.testing.assert_allclose(np.max(values), 0.1)
        if number == 4:
            np.testing.assert_allclose(np.min(values), -0.2)
            np.testing.assert_allclose(np.max(values), 0.2)
        if number == 5:
            assert np.count_nonzero(np.diff((do["port0"] & 2) > 0)) == 6
        if number >= 6:
            assert len(np.unique(values)) > 200
        if number >= 7:
            assert len(ao) > len(do) and np.any(do["port0"] == 2)
        if number == 8:
            assert plays("high", "scope_digital")
            assert plays("pulse", "scope_analog")
        if number == 9:
            assert all([s.time_dilation for s in spec.sections] == [1.0, 2.0]
                       for spec in specs)
        if number == 10:
            assert all(spec.sections[0].time_dilation_policy.value == "qua_logic"
                       for spec in specs)
            assert "if_(" in source and "else_()" in source
        if number <= 2:
            assert worker_samples == {"analog": 4, "digital": 4}
        return {"lesson": path.stem, "status": "PASS", "clock_rows": clock_rows,
                "ni_buffered_samples_per_channel": worker_samples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection-table", type=Path,
                        default=ROOT.parent / "connection_table.py")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "_compiled")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    connection_table = args.connection_table.resolve()
    original_hash = hashlib.sha256(connection_table.read_bytes()).hexdigest()
    reference = args.output_dir / "reference_connection_table.h5"
    compile_file(connection_table, reference, connection_table)
    results = []
    for lesson in sorted(ROOT.glob("[0-9][0-9]_*.py")):
        shot = args.output_dir / f"{lesson.stem}.h5"
        try:
            compile_file(lesson, shot, connection_table)
            result = inspect_shot(shot, reference)
            print(f"PASS {lesson.name}", flush=True)
        except Exception as exc:
            result = {"lesson": lesson.stem, "status": "FAIL", "error": traceback.format_exc()}
            print(f"FAIL {lesson.name}: {traceback.format_exc()}", flush=True)
        results.append(result)
    assert hashlib.sha256(connection_table.read_bytes()).hexdigest() == original_hash
    report = {
        "connection_table": str(connection_table), "connection_table_sha256": original_hash,
        "connection_table_unchanged": True, "python": sys.version,
        "versions": {p: importlib.metadata.version(p) for p in
                     ["labscript", "labscript-devices", "qm-qua", "numpy"]},
        "hardware_executed": False,
        "observed_ni_requirements": {
            "finite_timing_minimum_samples": 2,
            "pxie_6535_initial_transfer_minimum_samples": 4,
            "evidence": "Reported DAQmx errors -200077 and -200294; enforced by fake Task regression checks",
        },
        "validation_scope": "Local compilation, QUA serialization, NI buffers and real NI worker methods with fake tasks; no hardware or QOP server compilation",
        "passed": sum(r["status"] == "PASS" for r in results),
        "failed": sum(r["status"] == "FAIL" for r in results), "results": results,
        "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted(ROOT.glob("*.py"))},
    }
    (args.output_dir / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f'{report["passed"]} passed; {report["failed"]} failed. Hardware was not run.')
    return bool(report["failed"])


if __name__ == "__main__":
    raise SystemExit(main())
