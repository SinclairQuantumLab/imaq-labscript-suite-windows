"""Fetch QM results and write them back into shot HDF5 files."""

from __future__ import annotations

from typing import Protocol

import labscript_utils.h5_lock  # noqa: F401  # Ensure locking is active before h5py.
from user_devices.opx.result_io import ResultWriteMetadata, write_result_entry


class SupportsLogging(Protocol):
    def warning(self, msg: str, *args: object) -> None: ...
    def info(self, msg: str, *args: object) -> None: ...


class OpxResultExporter:
    """Export OPX/QM result handles into a shot HDF5 file."""

    def __init__(
        self,
        *,
        device_name: str,
        logger: SupportsLogging,
        result_export_timeout_s: float = 10.0,
    ) -> None:
        self.device_name = device_name
        self.logger = logger
        self.result_export_timeout_s = result_export_timeout_s
        self.exported_trace_names: set[str] = set()

    def reset(self) -> None:
        """Forget per-shot export bookkeeping."""
        self.exported_trace_names = set()

    def pending_traces(
        self,
        result_traces: list[ResultWriteMetadata],
    ) -> list[ResultWriteMetadata]:
        """Return result traces not yet written for this shot."""
        return [
            trace
            for trace in result_traces
            if trace["trace_name"] not in self.exported_trace_names
        ]

    def write_result_traces(
        self,
        device_group,
        result_handles,
        *,
        traces: list[ResultWriteMetadata],
    ) -> bool:
        """Fetch QM result handles and save them back into the shot file."""
        if not traces:
            return True

        try:
            completed = result_handles.wait_for_all_values(
                timeout=self.result_export_timeout_s
            )
        except TimeoutError:
            self.logger.warning(
                "Timed out waiting %.1fs for OPX results on %s.",
                self.result_export_timeout_s,
                self.device_name,
            )
            return False

        if not completed:
            self.logger.warning(
                "OPX results for %s did not finish cleanly; skipping result export.",
                self.device_name,
            )
            return False

        for trace in traces:
            trace_name = trace["trace_name"]
            if trace_name in self.exported_trace_names:
                continue
            handle = result_handles.get(trace["handle"])
            if handle is None:
                self.logger.warning(
                    "OPX result handle %r for trace %r was not returned by the job; "
                    "skipping export (no data was saved for this stream).",
                    trace["handle"],
                    trace.get("trace_name", trace["handle"]),
                )
                continue

            raw_values = handle.fetch_all()
            raw_timestamps = None

            if trace.get("timestamp_handle"):
                timestamp_handle = result_handles.get(trace["timestamp_handle"])
                if timestamp_handle is None:
                    self.logger.warning(
                        "OPX timestamp handle %r for trace %r was not returned; "
                        "exporting values without timestamps.",
                        trace["timestamp_handle"],
                        trace.get("trace_name", trace["handle"]),
                    )
                else:
                    raw_timestamps = timestamp_handle.fetch_all()

            write_result_entry(
                device_group,
                trace,
                raw_values,
                raw_timestamps=raw_timestamps,
                logger=self.logger,  # ty: ignore[invalid-argument-type]
            )
            self.exported_trace_names.add(trace_name)
        return True
