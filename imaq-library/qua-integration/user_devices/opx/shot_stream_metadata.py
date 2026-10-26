"""HDF5 metadata for per-shot OPX input-stream values and execution mode."""

from __future__ import annotations

import hashlib

import numpy as np
from user_devices.opx.execution_mode import (
    EXECUTION_MODE_EXECUTE,
    normalize_execution_mode,
)
from user_devices.opx.result_io import decode_optional_str_attr

type InputStreamScalarValue = bool | int | float
type InputStreamArrayValue = list[int] | list[float]
type InputStreamValue = InputStreamScalarValue | InputStreamArrayValue
InputStreamValues = dict[str, InputStreamValue]

INPUT_STREAMS_GROUP = "INPUT_STREAMS"
EXECUTION_MODE_ATTR = "execution_mode"
PROGRAM_FINGERPRINT_ATTR = "program_fingerprint"
MAX_INPUT_STREAM_ARRAY_LENGTH = 64


def compute_program_fingerprint(
    *,
    qua_config_bytes: bytes,
    qua_program_bytes: bytes | None = None,
) -> str:
    """Return a stable fingerprint for the executable QUA payload."""
    digest = hashlib.sha256()
    digest.update(qua_config_bytes)
    digest.update(b"\0")
    digest.update(qua_program_bytes or b"")
    return digest.hexdigest()


def _normalize_scalar_stream_value(
    stream_name: str,
    value: object,
    *,
    description: str,
) -> InputStreamScalarValue:
    if not isinstance(value, (bool, int, float)):
        raise TypeError(
            f"{description} value for {stream_name!r} must be bool, int, or float; "
            f"got {type(value)!r}."
        )
    return value


def _normalize_array_stream_value(
    stream_name: str,
    value: object,
    *,
    description: str,
) -> InputStreamArrayValue:
    if not isinstance(value, list):
        raise TypeError(
            f"{description} array value for {stream_name!r} must be a Python list; "
            f"got {type(value)!r}."
        )
    if not value:
        raise ValueError(
            f"{description} array value for {stream_name!r} must not be empty."
        )
    if len(value) > MAX_INPUT_STREAM_ARRAY_LENGTH:
        raise ValueError(
            f"{description} array value for {stream_name!r} exceeds "
            f"MAX_INPUT_STREAM_ARRAY_LENGTH={MAX_INPUT_STREAM_ARRAY_LENGTH} "
            f"(got {len(value)})."
        )
    if all(isinstance(entry, bool) for entry in value):
        normalized = [int(entry) for entry in value]
        return normalized
    if all(isinstance(entry, int) and not isinstance(entry, bool) for entry in value):
        return value
    if all(
        isinstance(entry, (int, float)) and not isinstance(entry, bool)
        for entry in value
    ):
        return [float(entry) for entry in value]
    raise TypeError(
        f"{description} array value for {stream_name!r} must contain only "
        "bool, int, or float entries of a uniform numeric type."
    )


def normalize_input_stream_values(
    values: InputStreamValues | None,
    *,
    description: str = "Input-stream",
) -> InputStreamValues:
    """Validate and normalize per-shot QUA input-stream values."""
    normalized: InputStreamValues = {}
    if not values:
        return normalized
    for stream_name, value in values.items():
        if not isinstance(stream_name, str) or not stream_name:
            raise ValueError(
                f"{description} names must be non-empty strings; got {stream_name!r}."
            )
        if isinstance(value, list):
            normalized[stream_name] = _normalize_array_stream_value(
                stream_name, value, description=description
            )
        else:
            normalized[stream_name] = _normalize_scalar_stream_value(
                stream_name, value, description=description
            )
    return normalized


def write_execution_mode(device_group, mode: str) -> None:
    device_group.attrs[EXECUTION_MODE_ATTR] = normalize_execution_mode(mode)


def read_execution_mode(device_group) -> str:
    raw_mode = device_group.attrs.get(EXECUTION_MODE_ATTR, EXECUTION_MODE_EXECUTE)
    return normalize_execution_mode(decode_optional_str_attr(raw_mode))


def write_input_stream_values(
    device_group,
    values: InputStreamValues,
) -> None:
    """Persist per-shot input-stream values under ``INPUT_STREAMS/``."""
    if INPUT_STREAMS_GROUP in device_group:
        del device_group[INPUT_STREAMS_GROUP]
    if not values:
        return

    streams_group = device_group.create_group(INPUT_STREAMS_GROUP)
    for stream_name, value in sorted(normalize_input_stream_values(values).items()):
        stream_group = streams_group.create_group(stream_name)
        if isinstance(value, list):
            if all(isinstance(entry, float) for entry in value):
                stream_group.attrs["dtype"] = "float_array"
                array = np.asarray(value, dtype=np.float64)
            else:
                stream_group.attrs["dtype"] = "int_array"
                array = np.asarray(value, dtype=np.int64)
            stream_group.attrs["array_length"] = len(value)
            stream_group.create_dataset("value", data=array)
            continue

        if isinstance(value, bool):
            stream_group.attrs["dtype"] = "bool"
            stream_group.create_dataset("value", data=np.uint8(value))
        elif isinstance(value, int):
            stream_group.attrs["dtype"] = "int"
            stream_group.create_dataset("value", data=np.int64(value))
        else:
            stream_group.attrs["dtype"] = "float"
            stream_group.create_dataset("value", data=np.float64(value))


def read_input_stream_values(device_group) -> InputStreamValues:
    """Load per-shot input-stream values from ``INPUT_STREAMS/``."""
    streams_group = device_group.get(INPUT_STREAMS_GROUP)
    if streams_group is None:
        return {}

    values: InputStreamValues = {}
    for stream_name, stream_group in streams_group.items():
        dtype = stream_group.attrs.get("dtype", "float")
        if isinstance(dtype, bytes):
            dtype = dtype.decode()
        raw_value = stream_group["value"][()]
        if dtype == "bool":
            values[str(stream_name)] = bool(raw_value)
        elif dtype == "int":
            values[str(stream_name)] = int(raw_value)
        elif dtype == "float":
            values[str(stream_name)] = float(raw_value)
        elif dtype == "int_array":
            length = int(stream_group.attrs.get("array_length", len(raw_value)))
            values[str(stream_name)] = [int(entry) for entry in raw_value[:length]]
        elif dtype == "float_array":
            length = int(stream_group.attrs.get("array_length", len(raw_value)))
            values[str(stream_name)] = [float(entry) for entry in raw_value[:length]]
        else:
            raise ValueError(
                f"Unsupported OPX input stream dtype {dtype!r} for {stream_name!r}."
            )
    return values
