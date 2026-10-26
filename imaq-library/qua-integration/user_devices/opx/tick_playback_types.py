"""Pydantic models for OPX pseudoclock tick playback metadata."""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from typing import Self

import numpy as np
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)


class TimeDilationPolicy(str, Enum):
    fixed = "fixed"
    input_stream = "input_stream"
    qua_logic = "qua_logic"


class PlaybackControlMode(str, Enum):
    section_table = "section_table"
    input_stream = "input_stream"


class PlaybackSection(BaseModel):
    """Nominal Labscript-time section with a time-dilation policy."""

    name: str
    start: float
    stop: float
    time_dilation: float = 1.0
    time_dilation_policy: TimeDilationPolicy = TimeDilationPolicy.fixed

    @field_validator("time_dilation")
    @classmethod
    def time_dilation_must_be_positive(
        cls, time_dilation: float, info: ValidationInfo
    ) -> float:
        if time_dilation <= 0:
            name = info.data.get("name", "<unknown>")
            raise ValueError(
                f"OPX playback section '{name}' time_dilation must be positive."
            )
        return time_dilation

    @model_validator(mode="after")
    def stop_not_before_start(self) -> Self:
        if self.stop < self.start:
            raise ValueError(
                f"OPX playback section '{self.name}' stops before it starts."
            )
        return self


class PlaybackSectionSpec(BaseModel):
    """One playback section after cycle conversion in the shot HDF5 spec."""

    name: str
    start_cycles: int
    stop_cycles: int
    time_dilation: float = Field(gt=0)
    time_dilation_policy: TimeDilationPolicy

    @model_validator(mode="after")
    def cycles_ordered(self) -> Self:
        if self.stop_cycles < self.start_cycles:
            raise ValueError(
                f"OPX playback section '{self.name}' stop_cycles is before start_cycles."
            )
        return self


class WorkerPlaybackSection(PlaybackSectionSpec):
    """Playback section record deserialized by the BLACS worker."""

    start: float
    stop: float


class InlineTickCommand(BaseModel):
    """One inline QUA command-buffer entry for a named playback section."""

    index: int = Field(ge=0)
    clock_line_name: str
    section_name: str


class TickSegment(BaseModel):
    """Compact pseudoclock tick timing derived from Labscript ``clock`` metadata."""

    start_s: float
    reps: int = Field(ge=1)
    step_cycles: int = Field(ge=0)
    first_wait_cycles: int = Field(default=0, ge=0)


class TickPlaybackConfig(BaseModel):
    """Shot-file metadata describing how the OPX should emit pseudoclock ticks."""

    clock_line_name: str
    tick_element: str
    tick_operation: str
    tick_pulse_cycles: int = Field(gt=0)
    default_time_dilation: float = Field(gt=0)
    control_mode: PlaybackControlMode = PlaybackControlMode.section_table
    time_dilation_input_stream: str = "opx_tick_time_dilation"
    auto_push_input_stream_defaults: bool = True
    timestamp_stream_name: str | None = None
    value_stream_name: str | None = None
    inline_playback: bool = False
    inline_max_sections: int | None = Field(default=None, gt=0)

    @field_validator("control_mode", mode="before")
    @classmethod
    def parse_control_mode(cls, value: object) -> PlaybackControlMode:
        if isinstance(value, PlaybackControlMode):
            return value
        try:
            return PlaybackControlMode(value)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported OPX tick playback control_mode '{value}'."
            ) from exc

    @model_validator(mode="after")
    def default_value_stream_name(self) -> Self:
        if self.timestamp_stream_name and self.value_stream_name is None:
            self.value_stream_name = f"{self.timestamp_stream_name}_values"
        return self


class TickPlaybackWorkerSpec(BaseModel):
    """Full tick-playback payload read from the shot HDF5 file by BLACS."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    clock_line_name: str
    tick_cycles: np.ndarray
    delta_cycles: np.ndarray
    tick_element: str
    tick_operation: str
    tick_pulse_cycles: int = Field(gt=0)
    default_time_dilation: float = Field(gt=0)
    time_dilation_input_stream: str
    timestamp_stream_name: str | None = None
    value_stream_name: str | None = None
    sections: list[WorkerPlaybackSection]
    control_mode: PlaybackControlMode = PlaybackControlMode.section_table
    auto_push_input_stream_defaults: bool = True
    inline_playback: bool = False
    inline_max_sections: int | None = Field(default=None, gt=0)
    inline_commands: list[InlineTickCommand] = Field(default_factory=list)
    section_tick_plans: dict[str, list[TickSegment]] = Field(default_factory=dict)


def normalise_playback_sections(
    sections: Sequence[PlaybackSection],
    stop_time: float,
    *,
    default_time_dilation: float,
    control_mode: PlaybackControlMode,
    clock_resolution: float,
) -> list[PlaybackSection]:
    """Return sorted playback sections, inserting a default section when absent."""
    if not sections:
        return [
            PlaybackSection(
                name="default",
                start=0.0,
                stop=stop_time,
                time_dilation=default_time_dilation,
                time_dilation_policy=(
                    TimeDilationPolicy.input_stream
                    if control_mode == PlaybackControlMode.input_stream
                    else TimeDilationPolicy.fixed
                ),
            )
        ]

    ordered = sorted(sections, key=lambda section: section.start)
    previous_stop = 0.0
    for section in ordered:
        if section.start < previous_stop - clock_resolution / 2:
            raise ValueError(
                f"OPX playback section '{section.name}' overlaps an earlier section."
            )
        previous_stop = max(previous_stop, section.stop)
    return ordered


def playback_section_for_tick_cycle(
    tick_cycle: int,
    sections: Sequence[PlaybackSectionSpec | WorkerPlaybackSection],
) -> PlaybackSectionSpec | WorkerPlaybackSection:
    """Return the playback section that owns one compiled tick cycle.

    Intervals use an exclusive stop: ``start_cycles <= tick_cycle < stop_cycles``.
    The final section also includes its stop cycle so the shot-end tick stays
    assigned.
    """
    if not sections:
        raise ValueError(
            "playback_section_for_tick_cycle requires at least one section."
        )

    last_index = len(sections) - 1
    for index, section in enumerate(sections):
        if index == last_index:
            if section.start_cycles <= tick_cycle <= section.stop_cycles:
                return section
        elif section.start_cycles <= tick_cycle < section.stop_cycles:
            return section
    return sections[-1]


def validation_error_message(exc: ValidationError) -> str:
    """Format a pydantic ``ValidationError`` as a single human-readable line."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    )
