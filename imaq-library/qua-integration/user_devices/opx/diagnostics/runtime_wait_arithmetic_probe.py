"""Isolate scaled-wait arithmetic; the QUA program emits no output instructions.

Simulation is the default. --execute-arithmetic queues only the audited arithmetic
program on an EXISTING idle QM; it never opens or reconfigures a QM, halts a job,
or arms NI hardware. This separates hardware arithmetic from wait execution.
"""

from __future__ import annotations

import argparse
import ast
import importlib.metadata
import json
from pathlib import Path

from qm import QuantumMachinesManager, SimulationConfig, qua
from user_devices.opx.qua_program_print import format_qua_program

BASES = [250_000, 8_486_053, (1 << 24) - 1, 1 << 24,
         (1 << 24) + 1, 31_250_000, (1 << 25) - 1]


def build_program():
    with qua.program() as program:
        scale = qua.declare(qua.fixed)
        selector = qua.declare(int)
        base_variable = qua.declare(int)
        product = qua.declare(int)
        rng = qua.Random(seed=42)
        raw = qua.declare_output_stream()
        literal_products = qua.declare_output_stream()
        variable_products = qua.declare_output_stream()
        scales = qua.declare_output_stream()
        qua.assign(selector, rng.rand_int(2))
        # Match mot_imaging_qua.py: a QUA branch assigns fixed scale = 1.
        with qua.if_(selector > 0):
            qua.assign(scale, 1)
        with qua.else_():
            qua.assign(scale, 1)
        qua.save(scale, scales)
        for base in BASES:
            qua.assign(base_variable, base)
            qua.save(base_variable, raw)
            qua.assign(product, qua.Cast.mul_int_by_fixed(base, scale))
            qua.save(product, literal_products)
            qua.assign(product, qua.Cast.mul_int_by_fixed(base_variable, scale))
            qua.save(product, variable_products)
        with qua.stream_processing():
            raw.save_all("raw")
            literal_products.save_all("literal_products")
            variable_products.save_all("variable_products")
            scales.save_all("scales")
    audit_arithmetic_only(program)
    return program


def audit_arithmetic_only(program):
    """Reject any generated QUA call outside this arithmetic/stream allowlist."""
    allowed_calls = {"program", "declare", "declare_output_stream", "assign",
                     "Random", "rand_int", "if_", "else_", "save",
                     "mul_int_by_fixed", "stream_processing", "save_all"}
    source = format_qua_program(program)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            name = (node.func.id if isinstance(node.func, ast.Name)
                    else node.func.attr if isinstance(node.func, ast.Attribute)
                    else "<unknown>")
            if name not in allowed_calls:
                raise RuntimeError(f"Non-arithmetic QUA instruction: {name}")
    return source


def simulation_config():
    # Configuration only; this program never plays the defined element.
    return {
        "controllers": {"con1": {"type": "opx1000", "fems": {
            3: {"type": "LF", "analog_outputs": {
                1: {"offset": 0.0, "output_mode": "direct"}}}}}},
        "elements": {"probe": {"singleInput": {"port": ("con1", 3, 1)}}},
    }


def fetch_report(job):
    job.wait_until("Done", timeout=30)
    results = {}
    for name in ("raw", "literal_products", "variable_products", "scales"):
        data = job.result_handles.get(name).fetch_all()
        if data.dtype.names:
            data = data["value"]
        results[name] = data.reshape(-1).tolist()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.50.252")
    parser.add_argument("--cluster", default="Cluster_1")
    parser.add_argument("--qm-id")
    parser.add_argument("--execute-arithmetic", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    program = build_program()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".qua.py").write_text(
        audit_arithmetic_only(program), encoding="utf-8")
    qmm = QuantumMachinesManager(host=args.host, cluster_name=args.cluster, timeout=20)
    metadata = {"qm_qua": importlib.metadata.version("qm-qua"),
                "server": str(qmm.version()), "expected": BASES,
                "mode": "execute-arithmetic" if args.execute_arithmetic else "simulate"}
    if args.execute_arithmetic:
        if not args.qm_id or args.qm_id not in qmm.list_open_qms():
            raise RuntimeError("An existing QM ID is required; no QM will be opened.")
        qm = qmm.get_qm(args.qm_id)
        if qm.get_running_job() is not None:
            raise RuntimeError("QM is busy; refusing to interrupt its job.")
        program_id = qm.compile(program)
        metadata.update(qm_id=args.qm_id, program_id=program_id)
        args.output.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        # Queueing preserves any job added concurrently; execute() is not used.
        job = qm.add_to_queue(program_id)
    else:
        job = qmm.simulate(simulation_config(), program, SimulationConfig(duration=20_000))
    metadata["job_id"] = job.id
    print("JOB", job.id, flush=True)
    metadata["results"] = fetch_report(job)
    metadata["products_match"] = all(
        metadata["results"][key] == BASES
        for key in ("raw", "literal_products", "variable_products"))
    args.output.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2), flush=True)


if __name__ == "__main__":
    main()
