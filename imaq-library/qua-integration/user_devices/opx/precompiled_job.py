"""Helpers for QM ``compile`` / ``add_compiled`` OPX execution."""

from __future__ import annotations

import time
from collections.abc import Mapping

from qm import Program
from user_devices.opx.shot_stream_metadata import InputStreamValue

PRECOMPILED_JOB_START_TIMEOUT_S = 30.0
QUEUE_POLL_INTERVAL_S = 0.01


def compile_qua_program(qm: object, program: Program) -> str:
    """Compile a QUA program on the cluster and return its ``program_id``."""
    compile_fn = getattr(qm, "compile", None)
    if not callable(compile_fn):
        raise TypeError(
            "The open QM object does not expose compile(); precompiled execution "
            "modes require a QM API with compile/add_compiled support."
        )
    program_id = compile_fn(program)
    if not isinstance(program_id, str) or not program_id:
        raise RuntimeError("QM compile() did not return a valid program_id.")
    return program_id


def enqueue_compiled_program(qm: object, program_id: str) -> object:
    """Append one compiled program to the QM queue without waiting for execution."""
    add_to_queue = getattr(qm, "add_to_queue", None)
    if callable(add_to_queue):
        return add_to_queue(program_id)

    queue = getattr(qm, "queue", None)
    if queue is None:
        raise RuntimeError(
            "The open QM object does not expose queue/add_to_queue APIs required "
            "for precompiled execution modes."
        )

    add_compiled = getattr(queue, "add_compiled", None)
    if not callable(add_compiled):
        raise TypeError(
            "The open QM queue does not expose add_compiled(); "
            "precompiled execution modes are unavailable on this QM API."
        )
    return add_compiled(program_id)


def get_running_job(qm: object) -> object | None:
    """Return the currently running QM job, if any."""
    get_running = getattr(qm, "get_running_job", None)
    if callable(get_running):
        return get_running()
    return None


def wait_for_running_job(
    qm: object, timeout: float = PRECOMPILED_JOB_START_TIMEOUT_S
) -> object:
    """Wait until the QM reports a running job or raise ``TimeoutError``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        running = get_running_job(qm)
        if running is not None:
            return running
        time.sleep(QUEUE_POLL_INTERVAL_S)
    raise TimeoutError(
        f"Timed out after {timeout:.1f}s waiting for a running OPX job to start."
    )


def wait_for_job_start(
    job: object, timeout: float = PRECOMPILED_JOB_START_TIMEOUT_S
) -> object:
    """Wait until a pending job object reports that execution has started."""
    wait_until = getattr(job, "wait_until", None)
    if callable(wait_until):
        wait_until({"Running", "Done", "Completed"}, timeout=timeout)
        return job

    wait_for_execution = getattr(job, "wait_for_execution", None)
    if callable(wait_for_execution):
        return wait_for_execution(timeout=timeout)

    running = wait_for_running_job(job, timeout=timeout)
    return running


def start_compiled_job(qm: object, program_id: str) -> object:
    """Queue and start one execution of a previously compiled ``program_id``."""
    pending_job = enqueue_compiled_program(qm, program_id)
    return wait_for_job_start(pending_job)


def push_input_stream(job: object, stream_name: str, value: InputStreamValue) -> None:
    """Push one scalar or array value to a QUA client input stream."""
    push = getattr(job, "push_to_input_stream", None)
    if not callable(push):
        raise TypeError(
            f"The active QM job does not expose push_to_input_stream(); "
            f"cannot push stream {stream_name!r}."
        )
    if isinstance(value, list):
        push(stream_name, list(value))
        return
    push(stream_name, value)


def push_input_streams(job: object, values: Mapping[str, InputStreamValue]) -> None:
    """Push all declared input-stream values."""
    for stream_name, value in values.items():
        push_input_stream(job, stream_name, value)
