"""Compare wait paths using zero-amplitude pulses on the existing scope output.

Uses an existing idle QM without changing its config. No NI clock or digital
marker is played. Every played analog waveform is multiplied by zero. Validate
the selected pulse has no marker and the output has zero DC offset before use.
"""
import argparse
import ast
import importlib.metadata
import json
from pathlib import Path
import time

from qm import QuantumMachinesManager, qua
from user_devices.opx.qua_program_print import format_qua_program
from user_devices.opx.tick_segment_compile import qua_wait_scaled_cycles

BASES = [(1 << 24) - 1, (1 << 24) + 100, (1 << 25) - 1, 31_250_000]
MODES = ["literal", "assigned", "calculated", "helper"]
ELEMENT = "scope_analog"
OPERATION = "pulse"


def validate_config(config):
    element = config["elements"][ELEMENT]
    sticky = element.get("sticky", {})
    assert not element.get("digitalInputs")
    assert not sticky.get("analog") and not sticky.get("digital")
    pulse = config["pulses"][element["operations"][OPERATION]]
    assert not pulse.get("digital_marker"), "Scope pulse must have no digital marker"
    port = element["singleInput"]["port"]
    controller, fem, output = port
    offset = config["controllers"][controller]["fems"][fem]["analog_outputs"][output]["offset"]
    assert offset == 0.0, "Scope output must have zero DC offset"
    return int(pulse["length"]) // 4


def build_program(helper_scan=False):
    cases = ([
        ("helper", 50_000_000, 0.5), ("helper", 50_000_000, 1.0),
        ("helper", 50_000_000, 2.0), ("helper", 50_000_000, 7.5),
        ("helper", 250_000_000, 1.0), ("helper", 1_250_000_000, 1.0),
    ] if helper_scan else [(mode, base, 1.0) for mode in MODES for base in BASES])
    with qua.program() as program:
        scale = qua.declare(qua.fixed)
        count = qua.declare(int)
        product = qua.declare(int)
        selector = qua.declare(int)
        rng = qua.Random(seed=42)
        counts = qua.declare_output_stream()
        times = qua.declare_output_stream()
        qua.assign(selector, rng.rand_int(2))
        with qua.if_(selector > 0):
            qua.assign(scale, 1)
        with qua.else_():
            qua.assign(scale, 1)
        for mode, base, scale_value in cases:
            with qua.if_(selector > 0):
                qua.assign(scale, scale_value)
            with qua.else_():
                qua.assign(scale, scale_value)
            qua.assign(count, base)
            if helper_scan:
                # Do not introduce the large literal multiplication this
                # chunked helper is specifically designed to avoid.
                qua.assign(product, round(base * scale_value))
            else:
                qua.assign(product, qua.Cast.mul_int_by_fixed(base, scale))
            qua.save(product, counts)
            qua.play(OPERATION * qua.amp(0), ELEMENT, timestamp_stream=times)
            if mode == "literal":
                qua.wait(base, ELEMENT)
            elif mode == "assigned":
                with qua.if_(count >= 4):
                    qua.wait(count, ELEMENT)
            elif mode == "calculated":
                with qua.if_(product >= 4):
                    qua.wait(product, ELEMENT)
            else:
                qua_wait_scaled_cycles(base, scale, ELEMENT, product)
            qua.play(OPERATION * qua.amp(0), ELEMENT, timestamp_stream=times)
        with qua.stream_processing():
            counts.save_all("products")
            times.save_all("pulse_times")
    # Check every play targets this single analog element and explicitly uses amp(0).
    source = format_qua_program(program)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "play":
            assert node.args[1].value == ELEMENT
            amplitudes = [kw.value for kw in node.keywords if kw.arg == "amplitude_scale"]
            assert len(amplitudes) == 1 and isinstance(amplitudes[0], ast.Constant)
            assert amplitudes[0].value == 0
    return program, source, cases


def fetch_values(job, name):
    data = job.result_handles.get(name).fetch_all()
    if data.dtype.names:
        data = data["value"]
    return data.reshape(-1).tolist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.50.252")
    parser.add_argument("--cluster", default="Cluster_1")
    parser.add_argument("--qm-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--helper-scan", action="store_true")
    args = parser.parse_args()
    qmm = QuantumMachinesManager(host=args.host, cluster_name=args.cluster, timeout=20)
    assert args.qm_id in qmm.list_open_qms()
    qm = qmm.get_qm(args.qm_id)
    assert qm.get_running_job() is None, "QM must be idle"
    pulse_cycles = validate_config(qm.get_config())
    program, source, cases = build_program(args.helper_scan)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".qua.py").write_text(source, encoding="utf-8")
    report = {"qm_qua": importlib.metadata.version("qm-qua"), "server": str(qmm.version()),
              "qm_id": args.qm_id, "pulse_cycles": pulse_cycles,
              "cases": [{"mode": mode, "base_cycles": base, "scale": scale}
                        for mode, base, scale in cases]}
    program_id = qm.compile(program)
    report["program_id"] = program_id
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    started = time.monotonic()
    job = qm.add_to_queue(program_id)
    report["job_id"] = job.id
    print("JOB", job.id, flush=True)
    job.wait_until("Done", timeout=30)
    report["wall_seconds"] = time.monotonic() - started
    times = fetch_values(job, "pulse_times")
    products = fetch_values(job, "products")
    assert len(times) == 2 * len(cases)
    rows = []
    for index, (mode, base, scale_value) in enumerate(cases):
        measured = times[2 * index + 1] - times[2 * index] - pulse_cycles
        expected = round(base * scale_value)
        rows.append({"mode": mode, "requested_cycles": base, "scale": scale_value,
                     "expected_scaled_cycles": expected, "product": products[index],
                     "measured_wait_cycles": measured,
                     "error_cycles": measured - expected})
    report.update(results=rows, pulse_times=times, execution_report=str(job.execution_report()))
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
