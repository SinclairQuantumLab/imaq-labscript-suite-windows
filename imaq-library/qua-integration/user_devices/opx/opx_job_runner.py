"""Start OPX QUA jobs for the supported execution modes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qm import Program
from user_devices.opx.execution_mode import EXECUTION_MODE_PRECOMPILED_PROGRAM_ID
from user_devices.opx.opx_job_status import ManagedJob
from user_devices.opx.precompiled_job import (
    compile_qua_program,
    push_input_streams,
    start_compiled_job,
)
from user_devices.opx.tick_playback_types import TimeDilationPolicy

if TYPE_CHECKING:
    from user_devices.opx.blacs_workers import ManagedQm, OPXWorker


class OpxJobRunner:
    """Start and configure OPX QUA jobs for each execution mode."""

    def __init__(self, worker: OPXWorker) -> None:
        self._worker = worker

    def start(self) -> None:
        """Start the current shot's QUA job using the selected execution mode."""
        worker = self._worker
        program = worker.blacs_qua_program
        if program is None:
            raise RuntimeError(
                f"OPX {worker.device_name} has no QUA program to execute."
            )

        if worker.qmm is None:
            raise RuntimeError("QM connection manager was not initialised.")
        if worker.blacs_qua_config is None:
            raise RuntimeError(
                f"OPX {worker.device_name} has no QM config for the current shot."
            )

        if worker.execution_mode == EXECUTION_MODE_PRECOMPILED_PROGRAM_ID:
            qm = self.get_or_open_qm()
            program_id = self.ensure_precompiled_program_id(qm, program)
            try:
                worker.job = start_compiled_job(qm, program_id)  # ty: ignore[invalid-assignment]
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                worker._program_id_cache.clear()
                program_id = self.ensure_precompiled_program_id(qm, program)
                try:
                    worker.job = start_compiled_job(qm, program_id)  # ty: ignore[invalid-assignment]
                except (OSError, RuntimeError, TypeError, ValueError) as retry_exc:
                    raise RuntimeError(
                        f"OPX {worker.device_name} failed to queue precompiled program "
                        f"{program_id!r} ({retry_exc!r})."
                    ) from retry_exc
                worker.logger.warning(
                    "OPX %s invalidated precompiled cache and recompiled after "
                    "add_compiled failure (%r).",
                    worker.device_name,
                    exc,
                )
            self.push_all_input_streams()
            return

        qm = worker.qmm.open_qm(worker.blacs_qua_config)
        try:
            worker.job = qm.execute(program)
        except Exception as exc:
            raise RuntimeError(
                f"OPX {worker.device_name} failed to queue the QUA program "
                f"({exc!r}). Search the log above for QOP compilation messages "
                f"from the 'qm' logger."
            ) from exc
        self.push_all_input_streams()

    def get_or_open_qm(self) -> ManagedQm:
        worker = self._worker
        if worker.qmm is None:
            raise RuntimeError("QM connection manager was not initialised.")
        if worker.blacs_qua_config is None:
            raise RuntimeError(
                f"OPX {worker.device_name} has no QM config for the current shot."
            )
        if worker._qm is None:
            worker._qm = worker.qmm.open_qm(worker.blacs_qua_config)
        return worker._qm

    def ensure_precompiled_program_id(
        self,
        qm: ManagedQm,
        program: Program,
        *,
        program_fingerprint: str | None = None,
    ) -> str:
        worker = self._worker
        fingerprint = program_fingerprint or worker.program_fingerprint
        if fingerprint is None:
            raise RuntimeError(
                f"OPX {worker.device_name} shot file has no program_fingerprint for a "
                "precompiled execution mode; recompile the shot with the current "
                "OPX device."
            )

        cached_program_id = worker._program_id_cache.get(fingerprint)
        if cached_program_id is not None:
            return cached_program_id

        program_id = compile_qua_program(qm, program)
        worker._program_id_cache[fingerprint] = program_id
        worker.logger.info(
            "Compiled OPX %s QUA program to program_id %s.",
            worker.device_name,
            program_id,
        )
        return program_id

    def push_segment_input_streams(
        self,
        job: ManagedJob,
        stream_values: dict[str, bool | int | float | list[int] | list[float]],
        *,
        include_tick_defaults: bool = False,
    ) -> None:
        if stream_values:
            push_input_streams(job, stream_values)
        if include_tick_defaults:
            self.push_tick_playback_defaults(job)

    def push_all_input_streams(self, job: ManagedJob | None = None) -> None:
        worker = self._worker
        active_job = job if job is not None else worker.job
        if active_job is None:
            return

        self.push_segment_input_streams(
            active_job,
            worker.input_stream_values,
            include_tick_defaults=True,
        )

    def push_tick_playback_defaults(self, job: ManagedJob | None = None) -> None:
        worker = self._worker
        specs = worker.tick_playback_specs
        if not specs:
            return
        active_job = job if job is not None else worker.job
        if active_job is None:
            return
        push = getattr(active_job, "push_to_input_stream", None)
        if not callable(push):
            worker.logger.warning(
                "The active QM job for %s does not expose push_to_input_stream(); "
                "input-stream-controlled tick sections may block.",
                worker.device_name,
            )
            return

        for spec in specs:
            if not spec.auto_push_input_stream_defaults:
                continue
            for section in spec.sections:
                if section.time_dilation_policy == TimeDilationPolicy.input_stream:
                    push(
                        spec.time_dilation_input_stream,
                        float(section.time_dilation),
                    )
