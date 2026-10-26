"""Normalize OPX/QM job status across QOP 2.x and 3.x APIs."""

from __future__ import annotations

from qm.api.v2.job_api.job_api import JobApi
from qm.jobs.running_qm_job import RunningQmJob

type ManagedJob = RunningQmJob | JobApi

_JOB_FINISHED_STATUSES = frozenset(
    {
        "completed",
        "done",
        "processing",
        "error",
        "canceled",
        "cancelled",
    }
)
_JOB_EXPORT_READY_STATUSES = frozenset({"completed", "done", "processing"})


def read_job_status(job: ManagedJob | None) -> str | None:
    """Return a normalized job-status string across QOP 2.x and 3.x job APIs."""
    if job is None:
        return None

    status = getattr(job, "status", None)
    if isinstance(status, str):
        return status

    get_status = getattr(job, "get_status", None)
    if callable(get_status):
        try:
            resolved = get_status()
        except (AttributeError, OSError, RuntimeError):
            return None
        if isinstance(resolved, str):
            return resolved
    return None


def job_has_finished(job: ManagedJob | None) -> bool:
    """Return whether BLACS should stop polling ``check_status`` for this job."""
    status = read_job_status(job)
    if status is None:
        return False
    return status.casefold() in _JOB_FINISHED_STATUSES


def job_ready_for_export(job: ManagedJob | None) -> bool:
    """Return whether result export should proceed for this job."""
    status = read_job_status(job)
    if status is None:
        return False
    return status.casefold() in _JOB_EXPORT_READY_STATUSES


def halt_job(job: ManagedJob | None) -> None:
    """Best-effort stop for both QOP 2.x and 3.x job objects."""
    if job is None:
        return
    for method_name in ("halt", "cancel"):
        method = getattr(job, method_name, None)
        if callable(method):
            method()
            return
