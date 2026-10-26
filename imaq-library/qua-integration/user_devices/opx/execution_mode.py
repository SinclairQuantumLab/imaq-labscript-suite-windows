"""Execution-mode constants for OPX BLACS runtime."""

from __future__ import annotations

from typing import Literal

ExecutionMode = Literal[
    "execute",
    "precompiled_program_id",
]

EXECUTION_MODE_EXECUTE: ExecutionMode = "execute"
EXECUTION_MODE_PRECOMPILED_PROGRAM_ID: ExecutionMode = "precompiled_program_id"

_SUPPORTED_EXECUTION_MODES = frozenset(
    {
        EXECUTION_MODE_EXECUTE,
        EXECUTION_MODE_PRECOMPILED_PROGRAM_ID,
    }
)


def normalize_execution_mode(mode: str | None) -> ExecutionMode:
    """Return a supported execution mode, defaulting to ``execute``."""
    if mode is None:
        return EXECUTION_MODE_EXECUTE
    normalized = str(mode).strip()
    if normalized not in _SUPPORTED_EXECUTION_MODES:
        raise ValueError(
            f"Unsupported OPX execution mode {mode!r}. "
            f"Expected one of {sorted(_SUPPORTED_EXECUTION_MODES)!r}."
        )
    return normalized  # type: ignore[return-value]


def uses_precompiled_program_id(mode: ExecutionMode | str) -> bool:
    """Return whether the mode reuses QM ``compile()`` / ``add_compiled()``."""
    normalized = normalize_execution_mode(str(mode))
    return normalized == EXECUTION_MODE_PRECOMPILED_PROGRAM_ID
