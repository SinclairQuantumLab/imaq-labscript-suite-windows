from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import labscript_utils.h5_lock  # noqa: F401  # Ensure locking is active before h5py.
import h5py
from blacs.tab_base_classes import Worker
from qm import Program, QuantumMachinesManager
from qm.api.v2.qm_api import QmApi
from qm.quantum_machine import QuantumMachine
from user_devices.opx.config_serialization import qm_config_to_json_bytes
from user_devices.opx.execution_mode import EXECUTION_MODE_EXECUTE
from user_devices.opx.opx_export_lock import acquire_export_lock
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
from user_devices.opx.precompiled_job import compile_qua_program, start_compiled_job
from user_devices.opx.qua_manual_programs import (
    KNOBS,
    MANUAL_PROGRAM_PUSH_INTERVAL_S,
    ManualChannelSpec,
    build_manual_program,
    default_knob_value,
    input_stream_name,
)
from user_devices.opx.qua_program_print import print_qua_program
from user_devices.opx.result_io import decode_optional_str_attr
from user_devices.opx.shot_stream_metadata import (
    compute_program_fingerprint,
    read_execution_mode,
    read_input_stream_values,
)
from user_devices.opx.tick_playback_types import TickPlaybackWorkerSpec

if TYPE_CHECKING:
    from user_devices.opx.result_io import ResultWriteMetadata

type ManagedQm = QuantumMachine | QmApi

# Inline tick playback can take several minutes to compile on QOP for multisection
# programs. The QM Python API defaults to 120 s.
QMM_TIMEOUT_S = 600.0


class OPXWorker(Worker):
    """BLACS runtime companion for the compile-time :class:`OPX` labscript device."""

    RESULT_EXPORT_TIMEOUT_S = 10.0
    QMM_LOG_LEVEL = "WARNING"
    DEBUG_QUA_PROGRAMS = False
    MANUAL_PUSH_INTERVAL_S = MANUAL_PROGRAM_PUSH_INTERVAL_S

    def _ensure_helpers(self) -> None:
        if not hasattr(self, "_result_exporter"):
            self._result_exporter = OpxResultExporter(
                device_name=self.device_name,
                logger=self.logger,
                result_export_timeout_s=self.RESULT_EXPORT_TIMEOUT_S,
            )
        if not hasattr(self, "_job_runner"):
            self._job_runner = OpxJobRunner(self)

    def _reset_precompiled_cache(self) -> None:
        """Drop any cached QM session state used by precompiled execution modes."""
        self._qm: ManagedQm | None = None
        self._program_id_cache: dict[str, str] = {}
        self._ensure_helpers()
        self._result_exporter.reset()

    def reset_precompiled_cache(self) -> bool:
        """Clear cached program_id state so the next shot recompiles on the cluster."""
        self._reset_precompiled_cache()
        return True

    def push_tick_playback_time_dilation(self, time_dilation: float) -> bool:
        """Queue one runtime time-dilation value for the generated QUA playback program."""
        specs = getattr(self, "tick_playback_specs", [])
        if self.job is None or not specs:
            return False
        push = getattr(self.job, "push_to_input_stream", None)
        if not callable(push):
            return False
        for spec in specs:
            push(spec.time_dilation_input_stream, float(time_dilation))
        return True

    def resume_tick_playback(self) -> bool:
        """Resume a custom QUA playback program that used `qua.pause()`."""
        if self.job is None:
            return False
        resume = getattr(self.job, "resume", None)
        if not callable(resume):
            return False
        resume()
        return True

    def init(self):
        """Initialise the worker once when BLACS starts.

        `create_worker()` merges this device's connection-table properties
        (set in `OPX.__init__`) into the worker args before `init()` runs, so
        `qm_host`/`qm_cluster_name`/`qm_port`/`is_master_pseudoclock` may
        already be set as instance attributes here. Use `getattr` rather than
        assigning fresh defaults so we don't clobber them.
        """
        self.logger.info("Initialising OPX BLACS worker.")
        self.qm_host = getattr(self, "qm_host", None)
        self.qm_cluster_name = getattr(self, "qm_cluster_name", None)
        self.qm_port = getattr(self, "qm_port", None)
        self.is_master_pseudoclock = getattr(self, "is_master_pseudoclock", True)
        self.qmm = self._try_connect_qmm()
        self.manual_channels: list[ManualChannelSpec] = getattr(
            self, "manual_channels", []
        )

        self.job: ManagedJob | None = None
        self.blacs_qua_config: QuaConfig | None = None
        self.blacs_qua_program: Program | None = None
        self.tick_playback_specs: list[TickPlaybackWorkerSpec] = []
        self.result_traces: list[ResultWriteMetadata] = []
        self.execution_mode = EXECUTION_MODE_EXECUTE
        self.input_stream_values = {}
        self.program_fingerprint: str | None = None
        self._qm: ManagedQm | None = None
        self._program_id_cache: dict[str, str] = {}
        self._manual_program_id_cache: dict[str, str] = {}
        self._manual_values: dict[str, object] = {}
        self._manual_program_wanted: bool = True
        self._manual_push_thread: threading.Thread | None = None
        self._manual_push_stop_event: threading.Event | None = None
        self._out_of_shot_job: ManagedJob | None = None
        self._ensure_helpers()
        self.check_status()
        self.logger.info("OPX BLACS worker initialised.")

    def _try_connect_qmm(self) -> QuantumMachinesManager | None:
        """Best-effort `QuantumMachinesManager` construction at BLACS startup.

        Runs before any shot has loaded, so failures (unreachable cluster,
        missing connection settings) must not prevent BLACS from starting.
        `transition_to_buffered` always reconstructs `self.qmm` from the shot
        file's own connection settings, so this is only for manual mode.
        """
        if not self.qm_host or not self.qm_cluster_name:
            return None
        try:
            return QuantumMachinesManager(
                host=self.qm_host,
                cluster_name=self.qm_cluster_name,
                port=self.qm_port,
                log_level=self.QMM_LOG_LEVEL,
                timeout=QMM_TIMEOUT_S,
            )
        except Exception:
            self.logger.exception(
                "OPX %s could not open a QM connection manager at BLACS "
                "startup; manual mode is unavailable until a shot runs.",
                self.device_name,
            )
            return None

    def program_manual(self, values: dict[str, float]) -> dict[str, float]:
        """Record changed front-panel values for the manual-mode QUA program.

        Front-panel channel names are used directly as QUA input-stream names
        (see `qua_manual_programs.py`). Values are *not* pushed to the job
        here: the generic manual program calls `advance_input_stream` for
        every knob on every loop iteration, so a one-off push of only the
        changed knob would stall the loop waiting for the other, unchanged
        knobs. Instead `_manual_program_push_loop`'s background thread is the
        sole pusher, continuously re-pushing everything recorded here.
        """
        values = dict(values or {})
        self._manual_values.update(values)
        self.logger.debug(
            "OPX %s manual values updated: %r",
            self.device_name,
            self._manual_values,
        )
        return dict(self._manual_values)  # ty: ignore[invalid-return-type]

    def check_remote_values(self) -> dict[str, float]:
        """Return the last front-panel values requested for manual-mode control.

        The OPX manual QUA program has no hardware readback, so this just
        replays whatever `program_manual` last successfully recorded.
        """
        return dict(self._manual_values)  # ty: ignore[invalid-return-type]

    def _push_manual_values_once(self, job: ManagedJob) -> None:
        """Push every declared knob's current (or default) value to `job` once."""
        push = getattr(job, "push_to_input_stream", None)
        if not callable(push):
            return
        config = self.blacs_qua_config
        for channel in self.manual_channels:
            for knob in KNOBS:
                name = input_stream_name(channel.name, knob)
                push(
                    name,
                    self._manual_values.get(
                        name,
                        default_knob_value(
                            knob,
                            config=config,  # ty: ignore[invalid-argument-type]
                            element=channel.element,
                        ),
                    ),
                )

    def _manual_program_push_loop(
        self, job: ManagedJob, stop_event: threading.Event
    ) -> None:
        """Continuously re-push manual values so the QUA program keeps advancing.

        Runs in a background thread until `stop_event` is set (from
        `stop_out_of_shot_job`). See `qua_manual_programs.py` for why a
        continuous pusher, rather than a one-off push per change, is required.
        """
        while not stop_event.wait(self.MANUAL_PUSH_INTERVAL_S):
            try:
                self._push_manual_values_once(job)
            except Exception:
                self.logger.exception(
                    "OPX %s manual program push thread failed; stopping.",
                    self.device_name,
                )
                return

    def _start_manual_push_thread(self, job: ManagedJob) -> None:
        self._stop_manual_push_thread()
        # Push once synchronously so the QUA program is not left blocking on
        # the first `advance_input_stream` while waiting for the thread's
        # initial sleep interval.
        self._push_manual_values_once(job)
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._manual_program_push_loop,
            args=(job, stop_event),
            name=f"opx-{self.device_name}-manual-push",
            daemon=True,
        )
        self._manual_push_stop_event = stop_event
        self._manual_push_thread = thread
        thread.start()

    def _stop_manual_push_thread(self) -> None:
        if self._manual_push_stop_event is not None:
            self._manual_push_stop_event.set()
        if self._manual_push_thread is not None and self._manual_push_thread.is_alive():
            self._manual_push_thread.join(timeout=self.MANUAL_PUSH_INTERVAL_S * 5)
        self._manual_push_stop_event = None
        self._manual_push_thread = None

    def stop_out_of_shot_job(self) -> bool:
        """Halt a QUA job started outside the buffered shot lifecycle."""
        self._stop_manual_push_thread()
        if self._out_of_shot_job is None:
            return False
        try:
            halt_job(self._out_of_shot_job)
        finally:
            self._out_of_shot_job = None
        self.logger.info("OPX %s halted out-of-shot QUA job.", self.device_name)
        return True

    def start_out_of_shot_compiled_job(
        self,
        program_id: str,
        input_stream_values: dict[str, bool | int | float | list[int] | list[float]]
        | None = None,
    ) -> bool:
        """Start one compiled QUA job outside the buffered shot lifecycle.

        Intended for BLACS manual control and calibration routines (for example
        tweezer homogenization) that must not disturb the precompiled program
        cache used by buffered shots.
        """
        if self.is_master_pseudoclock:
            self.logger.warning(
                "OPX %s is the master pseudoclock; out-of-shot jobs are for "
                "triggered secondary OPX devices only.",
                self.device_name,
            )
            return False

        self.stop_out_of_shot_job()
        qm = self._job_runner.get_or_open_qm()
        self._out_of_shot_job = start_compiled_job(qm, program_id)  # ty: ignore[invalid-assignment]
        if input_stream_values:
            self._job_runner.push_segment_input_streams(
                self._out_of_shot_job,  # ty: ignore[invalid-argument-type]
                input_stream_values,
            )
        self.logger.info(
            "OPX %s started out-of-shot compiled job %s.",
            self.device_name,
            program_id,
        )
        return True

    def apply_qm_config_overlay(self, config: QuaConfig) -> QuaConfig:
        """Return QM config with optional live calibration overlay applied.

        Subclasses or lab-specific worker mixins may override this to merge
        runtime calibration state (for example tweezer amplitudes) before
        opening the QM session.
        """
        return config

    def build_manual_qua_program(
        self, config: QuaConfig, channels: list[ManualChannelSpec]
    ) -> Program:
        """Build the QUA program used for BLACS manual-mode control.

        Default implementation delegates to the generic, config-derived
        builder in `qua_manual_programs.py`, which switches over each
        channel's declared operations and reads frequency/amplitude/phase/
        duration from input streams. Apparatus-specific worker subclasses may
        override this for manual behaviour that doesn't map onto that generic
        shape (for example a tweezer homogenization routine).
        """
        return build_manual_program(config, channels)  # ty: ignore[invalid-argument-type]

    def _ensure_manual_program_id(self, qm: ManagedQm) -> str:
        """Compile the manual QUA program once and cache its `program_id`.

        Cached separately from `_program_id_cache` (used by buffered shots)
        per `start_out_of_shot_compiled_job`'s contract. Keyed by a fingerprint
        of the config and program, so a changed QM config or manual-channel
        set recompiles automatically instead of silently reusing a stale
        `program_id`.
        """
        config = self.blacs_qua_config
        if config is None:
            raise RuntimeError(
                f"OPX {self.device_name} has no QM config yet; manual mode is "
                "unavailable until a shot has run."
            )
        program = self.build_manual_qua_program(config, self.manual_channels)
        program_bytes = bytes(program.to_protobuf(config))  # ty: ignore[invalid-argument-type]
        fingerprint = compute_program_fingerprint(
            qua_config_bytes=qm_config_to_json_bytes(config),
            qua_program_bytes=program_bytes,
        )
        cached_program_id = self._manual_program_id_cache.get(fingerprint)
        if cached_program_id is not None:
            return cached_program_id

        program_id = compile_qua_program(qm, program)
        self._manual_program_id_cache[fingerprint] = program_id
        self.logger.info(
            "Compiled OPX %s manual QUA program to program_id %s.",
            self.device_name,
            program_id,
        )
        return program_id

    def start_manual_program(self) -> bool:
        """(Re)start the generic manual-mode QUA job for this OPX's manual channels.

        Called automatically after every buffered shot (`transition_to_manual`)
        to restore manual control, since `transition_to_buffered` always halts
        the out-of-shot job first, and by the front panel's Start button.
        Marks the manual program as "wanted" (see `stop_manual_program`)
        regardless of whether starting is currently possible. No-op if there
        are no declared `OPXManualChannel`s, this OPX is the master
        pseudoclock (manual programs are for triggered secondaries only, like
        `start_out_of_shot_compiled_job`), or no shot has run yet (there is no
        QM config to compile against).
        """
        self._manual_program_wanted = True
        if not self.manual_channels or self.is_master_pseudoclock:
            return False
        if self.blacs_qua_config is None:
            return False
        qm = self._job_runner.get_or_open_qm()
        started = False
        try:
            program_id = self._ensure_manual_program_id(qm)
            started = self.start_out_of_shot_compiled_job(program_id)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._manual_program_id_cache.clear()
            try:
                program_id = self._ensure_manual_program_id(qm)
                started = self.start_out_of_shot_compiled_job(program_id)
            except (OSError, RuntimeError, TypeError, ValueError):
                self.logger.exception(
                    "OPX %s failed to start manual program after cache invalidation.",
                    self.device_name,
                )
                return False
            self.logger.warning(
                "OPX %s recovered stale manual program_id after cluster-side "
                "program loss (%r).",
                self.device_name,
                exc,
            )
        if started:
            self._start_manual_push_thread(self._out_of_shot_job)  # ty: ignore[invalid-argument-type]
        return started

    def stop_manual_program(self) -> bool:
        """Stop the manual-mode QUA job from the front panel's Stop button.

        Unlike the generic `stop_out_of_shot_job()` (used internally before
        every buffered shot), this also clears the "wanted" flag so
        `transition_to_manual` won't silently restart it after the next
        shot -- an explicit Stop should stay stopped.
        """
        self._manual_program_wanted = False
        return self.stop_out_of_shot_job()

    def reset_manual_program(self) -> bool:
        """Stop and immediately restart the manual-mode QUA job (Reset button)."""
        self.stop_out_of_shot_job()
        return self.start_manual_program()

    def manual_program_status(self) -> str:
        """Report a coarse status for the front panel's status indicator.

        One of `"stopped"` (no manual channels declared, or the user pressed
        Stop), `"waiting"` (wanted but not currently running -- no shot has
        provided a QM config yet, or a buffered shot currently owns the OPX),
        or `"running"` (the manual QUA job is active).
        """
        if not self.manual_channels or not self._manual_program_wanted:
            return "stopped"
        if self._out_of_shot_job is not None and not job_has_finished(
            self._out_of_shot_job
        ):
            return "running"
        return "waiting"

    def transition_to_buffered(self, device_name, h5_file, initial_values, fresh):
        """Load one compiled shot from HDF5 and prepare the OPX QUA job."""
        self.stop_out_of_shot_job()
        self.started = False
        self._ensure_helpers()
        self._result_exporter.reset()

        self.shot_file = h5_file
        with h5py.File(self.shot_file, "r") as f:
            grp = f[f"devices/{self.device_name}"]

            host = decode_optional_str_attr(grp.attrs.get("qm_host"))
            cluster_name = decode_optional_str_attr(grp.attrs.get("qm_cluster_name"))
            port = grp.attrs.get("qm_port")
            is_master = grp.attrs.get("is_master_pseudoclock", True)

            if port is not None:
                port = int(port)
            self.is_master_pseudoclock = bool(is_master)
            self.execution_mode = read_execution_mode(grp)
            self.input_stream_values = read_input_stream_values(grp)
            self.program_fingerprint = decode_optional_str_attr(
                grp.attrs.get("program_fingerprint")
            )
            if not host or not cluster_name:
                raise RuntimeError(
                    "The OPX shot file is missing QM connection metadata. "
                    "Recompile the shot after defining host/cluster_name in the connection table."
                )

            self.qm_host = str(host)
            self.qm_cluster_name = str(cluster_name)
            self.qm_port = port
            self.qmm = QuantumMachinesManager(
                host=self.qm_host,
                cluster_name=self.qm_cluster_name,
                port=self.qm_port,
                log_level=self.QMM_LOG_LEVEL,
                timeout=QMM_TIMEOUT_S,
            )

            self.tick_playback_specs = OpxShotLoader.read_tick_playback_specs(grp)

            if (
                "qua_config" not in grp
                and "qua_program" not in grp
                and not self.tick_playback_specs
            ):
                self.blacs_qua_config = None
                self.blacs_qua_program = None
                self.tick_playback_specs = []
                self.result_traces = []
                self.logger.info(
                    "No QUA payload stored for %s; skipping execution for this shot.",
                    self.device_name,
                )
                return {}

            if "qua_config" not in grp:
                raise RuntimeError(
                    f"OPX shot file for {self.device_name} contains executable "
                    "instructions but no QM config."
                )

            self.blacs_qua_config = OpxShotLoader.read_qua_config(grp["qua_config"])

            has_stored_qua_program = "qua_program" in grp
            if self.tick_playback_specs:
                if has_stored_qua_program:
                    self.blacs_qua_program = OpxShotLoader.load_stored_program(
                        grp["qua_program"]
                    )
                else:
                    self.blacs_qua_program = OpxShotLoader.build_tick_playback_program(
                        self.tick_playback_specs
                    )
            elif has_stored_qua_program:
                self.blacs_qua_program = OpxShotLoader.load_stored_program(
                    grp["qua_program"]
                )
            else:
                self.blacs_qua_program = None
            self.result_traces = OpxShotLoader.read_result_trace_metadata(grp)

            if self.DEBUG_QUA_PROGRAMS:
                print_qua_program(
                    self.blacs_qua_program,
                    device_name=self.device_name,
                    stage="compiled shot, before OPX execution",
                )

            if self.blacs_qua_program is None and not self.tick_playback_specs:
                self.logger.info(
                    "QM config stored for %s with no QUA program; "
                    "skipping execution for this shot.",
                    self.device_name,
                )
                return {}

            if not self.is_master_pseudoclock:
                self._job_runner.start()
                self.started = True
                self.logger.info(
                    "Armed secondary OPX %s during transition_to_buffered.",
                    self.device_name,
                )
        return {}

    def transition_to_manual(self):
        """Finish a buffered shot, export its data, and resume manual control.

        `transition_to_buffered` always halts the out-of-shot job before a
        shot runs (`start_out_of_shot_compiled_job` is for triggered
        secondaries only); restarting the manual-mode QUA job here, in a
        `finally`, restores it on every exit path -- normal completion, an
        unfinished job, or an export failure -- rather than leaving BLACS's
        manual controls disconnected until someone notices. Skipped if the
        user pressed Stop (`stop_manual_program`) before this shot ran.
        """
        try:
            return self._transition_to_manual_impl()
        finally:
            if self._manual_program_wanted:
                try:
                    self.start_manual_program()
                except Exception:
                    self.logger.exception(
                        "OPX %s failed to resume the manual-mode QUA job after "
                        "transition_to_manual.",
                        self.device_name,
                    )

    def _transition_to_manual_impl(self):
        self.logger.debug("OPX %s entering transition_to_manual.", self.device_name)
        self.started = False
        self._ensure_helpers()

        if self.job is None:
            self.logger.info(
                "OPX %s entered transition_to_manual with no active job; nothing to export.",
                self.device_name,
            )
            self.result_traces = []
            self.tick_playback_specs = []
            self.shot_file = None
            return True

        if not self.result_traces:
            self.logger.info(
                "OPX %s completed with no declared result traces; skipping HDF5 export.",
                self.device_name,
            )
            self.shot_file = None
            self.job = None
            self.tick_playback_specs = []
            return True

        job_status = read_job_status(self.job) or "unknown"
        self.logger.info(
            "OPX %s entering transition_to_manual with job status %s.",
            self.device_name,
            job_status,
        )

        if not job_ready_for_export(self.job):
            self.logger.warning(
                "OPX %s has not completed by transition_to_manual (status=%s). "
                "Skipping result export to avoid hanging BLACS.",
                self.device_name,
                job_status,
            )
            try:
                halt_job(self.job)
            except Exception:
                self.logger.exception(
                    "Failed to halt unfinished OPX job for %s.", self.device_name
                )
            self.shot_file = None
            self.job = None
            self.result_traces = []
            self.tick_playback_specs = []
            return True

        res = self.job.result_handles
        pending_traces = self._result_exporter.pending_traces(self.result_traces)
        if not pending_traces:
            self.logger.info(
                "OPX %s has no remaining result traces to export at transition_to_manual.",
                self.device_name,
            )
            self.shot_file = None
            self.job = None
            self.result_traces = []
            self.tick_playback_specs = []
            return True

        self.logger.info(
            "OPX %s waiting for export lock to write results.", self.device_name
        )
        with acquire_export_lock(self.shot_file):  # ty: ignore[invalid-argument-type]
            self.logger.info("OPX %s acquired export lock.", self.device_name)
            with h5py.File(self.shot_file, "a") as f:
                grp = f[f"devices/{self.device_name}"]
                exported = self._result_exporter.write_result_traces(
                    grp,
                    res,
                    traces=pending_traces,
                )
                if exported:
                    self.logger.info(
                        "OPX %s finished writing results to shot file.",
                        self.device_name,
                    )
                else:
                    self.logger.warning(
                        "Skipping HDF5 result export for %s because result handles were incomplete.",
                        self.device_name,
                    )

        self.shot_file = None
        self.job = None
        self.result_traces = []
        self.tick_playback_specs = []
        return True

    def abort_buffered(self):
        """Abort the current shot and run the usual cleanup path."""
        return self.transition_to_manual()

    def abort_transition_to_buffered(self):
        """Clean up partial state if loading a shot into buffered mode fails."""
        self.shot_file = None
        return True

    def start_run(self):
        """Start execution when this device is the primary pseudoclock."""
        self.logger.info("OPX sending start")
        self._ensure_helpers()

        if self.blacs_qua_config is None or self.blacs_qua_program is None:
            self.logger.info(
                "No QUA program configured for this OPX in the current shot."
            )
            self.job = None
            self.started = True
            return "started"

        if not self.is_master_pseudoclock:
            self.logger.info(
                "Secondary OPX already armed during transition_to_buffered."
            )
            self.started = True
            return "started"

        self._job_runner.start()
        self.started = True
        self.logger.info("OPX Worker self.started = True")
        return "started"

    def check_status(self):
        """Report whether the current QM job is still running."""
        if self.job is None:
            return 0

        if job_has_finished(self.job):
            self.logger.debug(
                "OPX %s job finished (status=%s).",
                self.device_name,
                read_job_status(self.job),
            )
            return 0
        self.logger.debug(
            "OPX %s job status is %s.",
            self.device_name,
            read_job_status(self.job),
        )
        return 1

    def _halt_job_best_effort(self, job: ManagedJob | None, *, context: str) -> None:
        """Stop one QM job without raising if the cluster is already gone."""
        if job is None or job_has_finished(job):
            return
        try:
            halt_job(job)
        except Exception:
            self.logger.exception(
                "OPX %s failed to halt %s job during shutdown.",
                self.device_name,
                context,
            )

    def _close_qm_connections(self) -> None:
        """Release any open QM session and connection-manager handles."""
        qm = getattr(self, "_qm", None)
        if qm is not None:
            close = getattr(qm, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    self.logger.exception(
                        "OPX %s failed to close QM session during shutdown.",
                        self.device_name,
                    )
            self._qm = None

        qmm = getattr(self, "qmm", None)
        if qmm is not None:
            close = getattr(qmm, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    self.logger.exception(
                        "OPX %s failed to close QM connection manager during shutdown.",
                        self.device_name,
                    )
            self.qmm = None

    def shutdown(self) -> bool:
        """Stop active QUA jobs and release QM connections when BLACS exits."""
        self.logger.info("OPX %s shutting down.", self.device_name)
        self._stop_manual_push_thread()
        try:
            self.stop_out_of_shot_job()
        except Exception:
            self.logger.exception(
                "OPX %s failed to stop out-of-shot job during shutdown.",
                self.device_name,
            )

        self._halt_job_best_effort(self.job, context="buffered")
        self.job = None
        self.shot_file = None
        self.started = False
        self.result_traces = []
        self.tick_playback_specs = []
        self._ensure_helpers()
        self._result_exporter.reset()
        self._close_qm_connections()
        return True
