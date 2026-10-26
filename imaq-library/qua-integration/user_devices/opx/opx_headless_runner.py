"""Run compiled OPX shots on QM hardware without BLACS or Run Manager."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import labscript_utils.h5_lock  # noqa: F401  # Must precede h5py.
import h5py
from qm import Program, QuantumMachinesManager
from qm.api.v2.qm_api import QmApi
from qm.quantum_machine import QuantumMachine
from user_devices.opx.execution_mode import EXECUTION_MODE_EXECUTE
from user_devices.opx.opx_job_runner import OpxJobRunner
from user_devices.opx.opx_job_status import (
    ManagedJob,
    halt_job,
    job_has_finished,
    job_ready_for_export,
    read_job_status,
)
from user_devices.opx.opx_result_exporter import OpxResultExporter
from user_devices.opx.opx_shot_loader import OpxShotLoader, QuaConfig
from user_devices.opx.result_io import (
    ResultWriteMetadata,
    decode_optional_str_attr,
)
from user_devices.opx.shot_stream_metadata import (
    read_execution_mode,
    read_input_stream_values,
)
from user_devices.opx.tick_playback_types import TickPlaybackWorkerSpec

logger = logging.getLogger(__name__)

type ManagedQm = QuantumMachine | QmApi

QMM_TIMEOUT_S = 600.0
DEFAULT_JOB_TIMEOUT_S = 600.0
DEFAULT_POLL_INTERVAL_S = 0.5
RESULT_EXPORT_TIMEOUT_S = 10.0


class _HeadlessLogger:
    """Minimal logger interface for :class:`OpxJobRunner` and exporters."""

    def __init__(self, name: str = "opx_headless") -> None:
        self._logger = logging.getLogger(name)

    def info(self, msg: str, *args: object) -> None:
        self._logger.info(msg, *args)

    def warning(self, msg: str, *args: object) -> None:
        self._logger.warning(msg, *args)

    def debug(self, msg: str, *args: object) -> None:
        self._logger.debug(msg, *args)

    def exception(self, msg: str, *args: object) -> None:
        self._logger.exception(msg, *args)


class HeadlessOpxWorker:
    """Duck-typed BLACS worker state used by the shared OPX runtime helpers."""

    def __init__(self, *, logger: _HeadlessLogger | None = None) -> None:
        self.logger = logger or _HeadlessLogger()
        self.device_name = ""
        self.shot_file: str | None = None
        self.qmm: QuantumMachinesManager | None = None
        self.qm_host: str | None = None
        self.qm_cluster_name: str | None = None
        self.qm_port: int | None = None
        self.is_master_pseudoclock = True
        self.job: ManagedJob | None = None
        self.blacs_qua_config: QuaConfig | None = None
        self.blacs_qua_program: Program | None = None
        self.tick_playback_specs: list[TickPlaybackWorkerSpec] = []
        self.result_traces: list[ResultWriteMetadata] = []
        self.execution_mode = EXECUTION_MODE_EXECUTE
        self.input_stream_values: dict[str, bool | int | float] = {}
        self.program_fingerprint: str | None = None
        self._qm: ManagedQm | None = None
        self._program_id_cache: dict[str, str] = {}
        self._result_exporter = OpxResultExporter(
            device_name="",
            logger=self.logger,
            result_export_timeout_s=RESULT_EXPORT_TIMEOUT_S,
        )
        self._job_runner = OpxJobRunner(self)  # ty: ignore[invalid-argument-type]


class OpxHeadlessRunner:
    """Compile-time shot HDF5 -> QM execution -> ``RESULTS/`` export."""

    def __init__(
        self,
        *,
        job_timeout_s: float = DEFAULT_JOB_TIMEOUT_S,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        logger: _HeadlessLogger | None = None,
    ) -> None:
        self._job_timeout_s = job_timeout_s
        self._poll_interval_s = poll_interval_s
        self._worker = HeadlessOpxWorker(logger=logger)

    @property
    def worker(self) -> HeadlessOpxWorker:
        return self._worker

    def load_shot(self, shot_path: str | Path, device_name: str) -> None:
        """Load one compiled shot from HDF5, mirroring BLACS ``transition_to_buffered``."""
        shot_path = Path(shot_path)
        logger.info("Loading OPX shot %s for device %s.", shot_path, device_name)
        worker = self._worker
        worker.device_name = device_name
        worker.shot_file = str(shot_path)
        worker._result_exporter.device_name = device_name
        worker._result_exporter.reset()
        worker._qm = None
        worker._program_id_cache = {}
        worker.job = None

        with h5py.File(worker.shot_file, "r") as shot_file:
            device_group = shot_file[f"devices/{device_name}"]

            host = decode_optional_str_attr(device_group.attrs.get("qm_host"))
            cluster_name = decode_optional_str_attr(
                device_group.attrs.get("qm_cluster_name")
            )
            port = device_group.attrs.get("qm_port")
            if port is not None:
                port = int(port)

            worker.is_master_pseudoclock = bool(
                device_group.attrs.get("is_master_pseudoclock", True)
            )
            worker.execution_mode = read_execution_mode(device_group)  # ty: ignore[invalid-assignment]
            worker.input_stream_values = read_input_stream_values(device_group)  # ty: ignore[invalid-assignment]
            worker.program_fingerprint = decode_optional_str_attr(
                device_group.attrs.get("program_fingerprint")
            )

            if not host or not cluster_name:
                raise RuntimeError(
                    "The OPX shot file is missing QM connection metadata. "
                    "Recompile the shot after defining host/cluster_name in the "
                    "connection table."
                )
            if worker.execution_mode != EXECUTION_MODE_EXECUTE:
                raise RuntimeError(
                    f"Headless runner only supports execution_mode={EXECUTION_MODE_EXECUTE!r}; "
                    f"got {worker.execution_mode!r}."
                )
            if not worker.is_master_pseudoclock:
                raise RuntimeError(
                    f"Headless runner does not support secondary OPX device {device_name!r}."
                )

            worker.qm_host = str(host)
            worker.qm_cluster_name = str(cluster_name)
            worker.qm_port = port
            logger.info(
                "Connecting to QM cluster %s@%s (port=%s).",
                worker.qm_cluster_name,
                worker.qm_host,
                worker.qm_port,
            )
            worker.qmm = QuantumMachinesManager(
                host=worker.qm_host,
                cluster_name=worker.qm_cluster_name,
                port=worker.qm_port,
                log_level="WARNING",
                timeout=QMM_TIMEOUT_S,
            )

            worker.tick_playback_specs = OpxShotLoader.read_tick_playback_specs(
                device_group
            )

            if "qua_config" not in device_group:
                raise RuntimeError(
                    f"OPX shot file for {device_name} contains executable "
                    "instructions but no QM config."
                )

            worker.blacs_qua_config = OpxShotLoader.read_qua_config(
                device_group["qua_config"]
            )

            has_stored_qua_program = "qua_program" in device_group
            if worker.tick_playback_specs:
                if has_stored_qua_program:
                    worker.blacs_qua_program = OpxShotLoader.load_stored_program(
                        device_group["qua_program"]
                    )
                else:
                    worker.blacs_qua_program = (
                        OpxShotLoader.build_tick_playback_program(
                            worker.tick_playback_specs
                        )
                    )
            elif has_stored_qua_program:
                worker.blacs_qua_program = OpxShotLoader.load_stored_program(
                    device_group["qua_program"]
                )
            else:
                worker.blacs_qua_program = None

            worker.result_traces = OpxShotLoader.read_result_trace_metadata(
                device_group
            )

            if worker.blacs_qua_program is None:
                raise RuntimeError(
                    f"OPX shot for {device_name!r} has no runnable QUA program."
                )

        logger.info(
            "Loaded OPX shot for %s (%d result trace(s), %d tick line(s)).",
            device_name,
            len(worker.result_traces),
            len(worker.tick_playback_specs),
        )

    def run(self) -> None:
        """Execute the loaded shot on QM hardware and export results to HDF5."""
        worker = self._worker
        if worker.shot_file is None:
            raise RuntimeError("No shot loaded; call load_shot() first.")

        logger.info(
            "Starting OPX QUA job on %s. QOP compilation can take several minutes "
            "for multi-section tick-playback programs.",
            worker.device_name,
        )
        worker._job_runner.start()
        logger.info(
            "OPX job queued on %s (status=%s); waiting for completion.",
            worker.device_name,
            read_job_status(worker.job) or "unknown",
        )
        self._wait_for_job()

        if worker.job is None:
            raise RuntimeError(f"OPX {worker.device_name} did not start a QM job.")

        if not worker.result_traces:
            worker.logger.info(
                "OPX %s completed with no declared result traces; skipping export.",
                worker.device_name,
            )
            return

        if not job_ready_for_export(worker.job):
            status = read_job_status(worker.job) or "unknown"
            try:
                halt_job(worker.job)
            except Exception:
                worker.logger.exception(
                    "Failed to halt unfinished OPX job for %s.", worker.device_name
                )
            raise RuntimeError(
                f"OPX {worker.device_name} job finished with status {status!r}, "
                "which is not ready for result export."
            )

        pending_traces = worker._result_exporter.pending_traces(worker.result_traces)
        if not pending_traces:
            return

        logger.info(
            "Exporting %d OPX result trace(s) from %s into the shot HDF5 file.",
            len(pending_traces),
            worker.device_name,
        )
        from user_devices.opx.opx_export_lock import acquire_export_lock

        with (
            acquire_export_lock(worker.shot_file),
            h5py.File(worker.shot_file, "a") as shot_file,
        ):
            device_group = shot_file[f"devices/{worker.device_name}"]
            exported = worker._result_exporter.write_result_traces(
                device_group,
                worker.job.result_handles,
                traces=pending_traces,
            )
            if not exported:
                raise RuntimeError(
                    f"OPX {worker.device_name} result export did not complete cleanly."
                )

    def _wait_for_job(self) -> None:
        worker = self._worker
        deadline = time.monotonic() + self._job_timeout_s
        next_status_log = time.monotonic()
        while time.monotonic() < deadline:
            if worker.job is not None and job_has_finished(worker.job):
                logger.info(
                    "OPX job on %s finished (status=%s).",
                    worker.device_name,
                    read_job_status(worker.job) or "unknown",
                )
                return
            if time.monotonic() >= next_status_log:
                logger.info(
                    "Still waiting for OPX job on %s (status=%s).",
                    worker.device_name,
                    read_job_status(worker.job) or "unknown",
                )
                next_status_log = time.monotonic() + 30.0
            time.sleep(self._poll_interval_s)

        if worker.job is not None:
            try:
                halt_job(worker.job)
            except Exception:
                worker.logger.exception(
                    "Failed to halt timed-out OPX job for %s.", worker.device_name
                )
        raise TimeoutError(
            f"OPX {worker.device_name} job did not finish within "
            f"{self._job_timeout_s:.0f}s."
        )


def run_inline_experiment_shot(
    shot_path: str | Path,
    device_name: str,
    *,
    job_timeout_s: float = DEFAULT_JOB_TIMEOUT_S,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
) -> None:
    """Load, execute, and export one inline OPX-master shot."""
    runner = OpxHeadlessRunner(
        job_timeout_s=job_timeout_s,
        poll_interval_s=poll_interval_s,
    )
    runner.load_shot(shot_path, device_name)
    runner.run()
