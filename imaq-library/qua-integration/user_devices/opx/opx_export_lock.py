"""Filesystem lock used to serialize OPX result export across BLACS workers."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager


def export_lock_path(shot_file: str) -> str:
    """Return the per-shot lock path used to serialize HDF5 result writes."""
    return f"{shot_file}.opx_export.lock"


@contextmanager
def acquire_export_lock(
    shot_file: str,
    *,
    timeout_s: float = 30.0,
    stale_after_s: float = 300.0,
) -> Iterator[None]:
    """Serialize result export across OPX workers using a lock file.

    BLACS may run multiple OPX workers in parallel, and on Windows the HDF5
    append open can fail if two workers touch the same shot file at the same
    time. This lock ensures only one worker opens the file for export at once.
    """
    lock_path = export_lock_path(shot_file)
    start_time = time.monotonic()
    sleep_s = 0.05
    fd = None

    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, f"pid={os.getpid()} time={time.time()}".encode())
            break
        except FileExistsError:
            try:
                age_s = time.time() - os.path.getmtime(lock_path)
            except OSError:
                age_s = 0.0

            if age_s > stale_after_s:
                try:
                    os.remove(lock_path)
                    continue
                except OSError:
                    pass

            if time.monotonic() - start_time > timeout_s:
                raise TimeoutError(
                    f"Timed out waiting for OPX export lock '{lock_path}'."
                )

            time.sleep(sleep_s)
            sleep_s = min(sleep_s * 1.5, 0.5)

    try:
        yield
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.remove(lock_path)
        except OSError:
            pass
