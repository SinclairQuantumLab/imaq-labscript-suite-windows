"""Load OPX shot metadata from compiled HDF5 files."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np
from pydantic import ValidationError
from qm import Program
from user_devices.opx.config_serialization import (
    DATASET_ATTR_SERIALIZATION,
    qm_config_from_json_bytes,
)
from user_devices.opx.qua_tick_programs import build_tick_only_fallback_program
from user_devices.opx.result_io import (
    ResultWriteMetadata,
    read_result_metadata_attrs,
)
from user_devices.opx.tick_playback_types import (
    InlineTickCommand,
    TickPlaybackWorkerSpec,
    WorkerPlaybackSection,
    validation_error_message,
)
from user_devices.opx.tick_segment_compile import read_section_tick_plans_hdf5

if TYPE_CHECKING:
    import h5py
    from qm.type_hinting.config_types import ControllerQuaConfig, FullQuaConfig

type QuaConfig = "FullQuaConfig | ControllerQuaConfig"


class OpxShotLoader:
    """Read compile-time OPX metadata persisted in a shot HDF5 device group."""

    @staticmethod
    def decode_h5_attr(
        value: str | bytes | np.generic | float | bool | None,
    ) -> str | int | float | bool | None:
        """Return HDF5 attribute values as normal Python objects where possible."""
        if isinstance(value, bytes):
            return value.decode()
        if isinstance(value, np.generic):
            item = value.item()
            if isinstance(item, (str, int, float, bool)) or item is None:
                return item
            return str(item)
        return value

    @classmethod
    def require_h5_attr(
        cls,
        attrs: dict[str, str | int | float | bool | None],
        key: str,
    ) -> str | int | float | bool:
        value = attrs[key]
        if value is None:
            raise KeyError(f"Missing required HDF5 attribute '{key}'.")
        return value

    @classmethod
    def read_result_trace_metadata(
        cls, device_group: h5py.Group
    ) -> list[ResultWriteMetadata]:
        """Read result-export instructions written by ``OPX.generate_code()``."""
        metadata_group = device_group.get("RESULT_METADATA")
        if metadata_group is None:
            return []

        result_traces: list[ResultWriteMetadata] = []
        for trace_name, trace_group in metadata_group.items():
            attrs = read_result_metadata_attrs(trace_group)
            result_traces.append(
                {
                    "trace_name": trace_name,
                    "handle": str(attrs["handle"]),
                    "clock_line_name": attrs["clock_line_name"],
                    "sample_period": attrs["sample_period"],
                    "t0": attrs["t0"],
                    "timestamp_scale": attrs["timestamp_scale"],
                    "align_to_first_timestamp": attrs["align_to_first_timestamp"],
                    "timestamp_handle": attrs["timestamp_handle"],
                }
            )
        return result_traces

    @classmethod
    def read_tick_playback_specs(
        cls, device_group: h5py.Group
    ) -> list[TickPlaybackWorkerSpec]:
        """Read OPX tick-playback instructions written by the labscript device."""
        playback_group = device_group.get("TICK_PLAYBACK")
        if playback_group is None:
            return []

        clock_lines_group = playback_group.get("CLOCK_LINES")
        if clock_lines_group is None:
            raise RuntimeError(
                "OPX TICK_PLAYBACK schema is missing CLOCK_LINES. "
                "Recompile the shot with the line-indexed OPX pseudoclock device."
            )

        return [
            cls.read_tick_playback_line_spec(str(clock_line_name), line_group)
            for clock_line_name, line_group in sorted(clock_lines_group.items())
        ]

    @classmethod
    def read_tick_playback_line_spec(
        cls,
        clock_line_name: str,
        playback_group: h5py.Group,
    ) -> TickPlaybackWorkerSpec:
        """Read one line-local tick-playback spec from a CLOCK_LINES subgroup."""
        attrs = {
            key: cls.decode_h5_attr(value)
            for key, value in playback_group.attrs.items()
        }
        sections = []
        sections_group = playback_group.get("SECTIONS")
        if sections_group is not None:
            for _, section_group in sorted(sections_group.items()):
                section_attrs = {
                    key: cls.decode_h5_attr(value)
                    for key, value in section_group.attrs.items()
                }
                try:
                    sections.append(
                        WorkerPlaybackSection.model_validate(
                            {
                                "name": cls.require_h5_attr(section_attrs, "name"),
                                "start": cls.require_h5_attr(section_attrs, "start"),
                                "stop": cls.require_h5_attr(section_attrs, "stop"),
                                "start_cycles": cls.require_h5_attr(
                                    section_attrs, "start_cycles"
                                ),
                                "stop_cycles": cls.require_h5_attr(
                                    section_attrs, "stop_cycles"
                                ),
                                "time_dilation": cls.require_h5_attr(
                                    section_attrs, "time_dilation"
                                ),
                                "time_dilation_policy": cls.require_h5_attr(
                                    section_attrs, "time_dilation_policy"
                                ),
                            }
                        )
                    )
                except ValidationError as exc:
                    raise RuntimeError(validation_error_message(exc)) from exc

        inline_commands = []
        commands_group = playback_group.get("INLINE_COMMANDS")
        if commands_group is not None:
            for _, command_group in sorted(commands_group.items()):
                command_attrs = {
                    key: cls.decode_h5_attr(value)
                    for key, value in command_group.attrs.items()
                }
                inline_commands.append(
                    InlineTickCommand.model_validate(
                        {
                            "index": cls.require_h5_attr(command_attrs, "index"),
                            "clock_line_name": cls.require_h5_attr(
                                command_attrs, "clock_line_name"
                            ),
                            "section_name": cls.require_h5_attr(
                                command_attrs, "section_name"
                            ),
                        }
                    )
                )

        try:
            return TickPlaybackWorkerSpec.model_validate(
                {
                    "clock_line_name": cls.require_h5_attr(attrs, "clock_line_name"),
                    "tick_cycles": np.asarray(
                        playback_group["tick_cycles"][()], dtype=np.int64
                    ),
                    "delta_cycles": np.asarray(
                        playback_group["delta_cycles"][()], dtype=np.int64
                    ),
                    "tick_element": cls.require_h5_attr(attrs, "tick_element"),
                    "tick_operation": cls.require_h5_attr(attrs, "tick_operation"),
                    "tick_pulse_cycles": cls.require_h5_attr(
                        attrs, "tick_pulse_cycles"
                    ),
                    "default_time_dilation": cls.require_h5_attr(
                        attrs, "default_time_dilation"
                    ),
                    "control_mode": attrs.get("control_mode", "section_table"),
                    "time_dilation_input_stream": attrs.get(
                        "time_dilation_input_stream", "opx_tick_time_dilation"
                    ),
                    "auto_push_input_stream_defaults": attrs.get(
                        "auto_push_input_stream_defaults", True
                    ),
                    "timestamp_stream_name": attrs.get("timestamp_stream_name"),
                    "value_stream_name": attrs.get("value_stream_name"),
                    "inline_playback": attrs.get("inline_playback", False),
                    "sections": sections,
                    "inline_commands": inline_commands,
                    "section_tick_plans": read_section_tick_plans_hdf5(
                        playback_group, inline_commands
                    ),
                }
            )
        except ValidationError as exc:
            raise RuntimeError(validation_error_message(exc)) from exc

    @staticmethod
    def read_qua_config(dataset: h5py.Dataset) -> QuaConfig:
        """Read the tagged JSON QM config payload from a shot file."""
        raw_bytes = bytes(dataset[()].tobytes())
        serialization = dataset.attrs.get("serialization")
        if isinstance(serialization, bytes):
            serialization = serialization.decode()
        if serialization == DATASET_ATTR_SERIALIZATION:
            return qm_config_from_json_bytes(raw_bytes)
        raise RuntimeError(
            "OPX shot file contains unsupported QM config serialisation "
            f"{serialization!r}. Recompile the shot with the production OPX device."
        )

    @staticmethod
    def load_stored_program(dataset: h5py.Dataset) -> Program:
        """Rebuild a protobuf-encoded QUA program stored in a shot file."""
        return Program.from_protobuf(bytes(dataset[()].tobytes()))

    @staticmethod
    def build_tick_playback_program(
        specs: Sequence[TickPlaybackWorkerSpec],
    ) -> Program:
        """Build the runnable QUA program for a tick-only playback shot."""
        if not specs:
            raise RuntimeError("OPX tick playback requires at least one playback spec.")
        return build_tick_only_fallback_program(specs=specs)
