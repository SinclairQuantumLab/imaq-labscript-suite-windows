"""Shared HDF5 I/O helpers for OPX/QM result payloads.

This module is the contract between the OPX BLACS worker and the reader-side
tools (Runviewer, Lyse analysis, or any future post-processing code).

Design goals:

1. Preserve fetched QM results with as little interpretation as possible.
   The worker should store what QM returned, not force every result into a
   1D `times`/`values` trace representation.
2. Keep the HDF5 layout simple.
   QM `fetch_all()` results are expected to be numpy arrays, numpy scalars,
   plain numeric scalars, or `None`. Those are written directly whenever HDF5
   supports them.
3. Stay robust against unexpected SDK changes.
   If a future QM version returns an unsupported value, store a repr-string
   fallback instead of failing the whole shot export.
4. Centralise interpretation logic.
   Reader code should not duplicate ad-hoc conversions. Instead, they can read
   a result entry via `read_result_entry()` and ask `build_trace_arrays()`
   whether the stored payload can be interpreted as a plottable 1D trace.

The HDF5 structure written by `write_result_entry()` is:

- `devices/<device_name>/RESULTS/<trace_name>/`
  - attrs: metadata copied from the compile-time registration
  - `values`: the fetched QM payload
  - optional `timestamps`: a separately fetched timestamp payload

The format intentionally focuses on the current QM result contract:

- simple scalar results
- 1D and multidimensional numeric arrays
- structured timestamped arrays
- optional missing values (`None`)
"""

import warnings
from collections.abc import Iterator, Sequence
from typing import (
    Any,
    Protocol,
    TypedDict,
)

import labscript_utils.h5_lock  # noqa: F401  # Must be imported before h5py in labscript processes.
import h5py
import numpy as np

TraceArrays = tuple[np.ndarray, np.ndarray]
TraceSegments = list[TraceArrays]
H5Node = h5py.Group | h5py.Dataset


class SupportsWarning(Protocol):
    def warning(self, message: str) -> Any: ...


class ResultWriteMetadata(TypedDict):
    """Compile-time metadata used when exporting one QM result handle."""

    trace_name: str
    handle: str
    clock_line_name: str | None
    sample_period: float
    t0: float
    timestamp_scale: float
    align_to_first_timestamp: bool
    timestamp_handle: str | None


class ResultEntry(TypedDict):
    """Reader-side result entry including fetched payload handles."""

    trace_name: str
    handle: str | None
    clock_line_name: str | None
    sample_period: float
    t0: float
    timestamp_scale: float
    align_to_first_timestamp: bool
    timestamp_handle: str | None
    values: Any
    timestamps: Any | None


RESULTS_GROUP_NAME: str = "RESULTS"
STRING_DTYPE = h5py.string_dtype(encoding="utf-8")
TIMESTAMP_FIELD_CANDIDATES: tuple[str, ...] = ("timestamp", "timestamps", "time", "t")
VALUE_FIELD_CANDIDATES: tuple[str, ...] = ("value", "values", "data")


def _warn(logger: SupportsWarning | None, message: str) -> None:
    """Emit a warning through BLACS logging when available, else via warnings."""
    if logger is not None:
        logger.warning(message)
    else:
        warnings.warn(message, RuntimeWarning, stacklevel=2)


def _delete_if_present(group: h5py.Group, name: str) -> None:
    """Remove an existing child entry so rewrites replace stale data cleanly."""
    if name in group:
        del group[name]


def _normalise_bytes(value: bytes | np.bytes_) -> str | bytes:
    """Decode bytes to UTF-8 when possible, otherwise preserve raw bytes."""
    if isinstance(value, np.bytes_):
        value = bytes(value)
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value


def _decode_attr_value(value: Any) -> Any:
    """Decode byte-valued HDF5 attributes into normal Python strings."""
    if isinstance(value, (bytes, np.bytes_)):
        return _normalise_bytes(value)
    return value


def decode_optional_str_attr(value: Any) -> str | None:
    """Decode an HDF5 attribute expected to be a string, bytes, or ``None``.

    Shared by every reader in this package that stores optional string
    metadata (result-trace handles, execution mode, connection settings) so the bytes-vs-str handling lives
    in exactly one place.
    """
    decoded = _decode_attr_value(value)
    return decoded if isinstance(decoded, str) else None


def _create_serialized_dataset(
    parent: h5py.Group,
    name: str,
    data: Any,
    serialization: str,
    **kwargs: Any,
) -> h5py.Dataset:
    """Create a dataset and record how the value was serialised."""
    dataset = parent.create_dataset(name, data=data, **kwargs)
    dataset.attrs["serialization"] = serialization
    return dataset


def _create_serialized_group(
    parent: h5py.Group, name: str, serialization: str
) -> h5py.Group:
    """Create a subgroup and record how the value was serialised."""
    subgroup = parent.create_group(name)
    subgroup.attrs["serialization"] = serialization
    return subgroup


def _write_ndarray_value(
    parent: h5py.Group,
    name: str,
    value: np.ndarray,
    logger: SupportsWarning | None = None,
) -> None:
    """Serialise numpy arrays directly when HDF5 supports their dtype."""
    try:
        _create_serialized_dataset(parent, name, value, "ndarray")
        return
    except TypeError:
        _warn(
            logger,
            f"Falling back to repr-string serialisation for array result '{name}' "
            f"with unsupported dtype {value.dtype!s}.",
        )
        _create_serialized_dataset(
            parent, name, repr(value), "repr", dtype=STRING_DTYPE
        )


def _write_fallback_value(
    parent: h5py.Group,
    name: str,
    value: Any,
    logger: SupportsWarning | None = None,
) -> None:
    """Fallback serialisation for unexpected non-array/scalar values."""
    _warn(
        logger,
        f"Falling back to repr-string serialisation for unexpected result '{name}' "
        f"of type {type(value).__name__}.",
    )
    _create_serialized_dataset(parent, name, repr(value), "repr", dtype=STRING_DTYPE)


def _write_value(
    parent: h5py.Group,
    name: str,
    value: Any,
    logger: SupportsWarning | None = None,
) -> None:
    """Serialise one QM result value into an HDF5 dataset or subgroup.

    QM `fetch_all()` is expected to return one of:

    - `None`
    - a numpy array
    - a numpy scalar
    - a plain numeric scalar

    These are written directly when possible. Unexpected values fall back to a
    repr-string so the shot remains inspectable instead of failing hard during
    result export.

    Each stored node gets a `serialization` attribute so `_read_value()` can
    reconstruct an equivalent Python value later.
    """
    _delete_if_present(parent, name)

    if value is None:
        # Represent `None` as an empty group plus a marker attribute, since HDF5
        # has no native null object type.
        _create_serialized_group(parent, name, "none")
        return

    if isinstance(value, np.ndarray):
        _write_ndarray_value(parent, name, value, logger=logger)
        return

    if isinstance(value, np.generic):
        # Numpy scalars are HDF5-friendly but are not instances of Python's
        # built-in numeric types, so handle them separately.
        _create_serialized_dataset(parent, name, value, "numpy_scalar")
        return

    if isinstance(value, (bool, int, float, complex)):
        _create_serialized_dataset(parent, name, value, "python_scalar")
        return

    # Last-resort fallback: preserve something human-readable instead of failing
    # the entire shot export for one unsupported value.
    _write_fallback_value(parent, name, value, logger=logger)


def _read_value(node: H5Node) -> Any:
    """Inverse of `_write_value()`: rebuild a Python value from HDF5 storage."""
    if isinstance(node, h5py.Dataset):
        value = node[()]
        if isinstance(value, (bytes, np.bytes_)):
            # String-like datasets come back as bytes from h5py, so decode when
            # possible for nicer downstream handling.
            return _normalise_bytes(value)
        return value

    serialization = _decode_attr_value(node.attrs.get("serialization", ""))

    if serialization == "none":
        return None

    raise RuntimeError(f"Unsupported OPX result serialization: {serialization!r}")


def write_result_metadata_attrs(group: h5py.Group, trace: ResultWriteMetadata) -> None:
    """Write the metadata fields shared by `RESULTS/` and `RESULT_METADATA/` groups.

    Used both for the compile-time export instructions (`OPX.generate_code()`,
    one group per registered `add_result_trace()` call) and the runtime
    `RESULTS/` entries `write_result_entry()` writes after a shot completes, so
    the two never drift out of sync with each other.
    """
    group.attrs["handle"] = trace["handle"]
    if trace.get("clock_line_name") is not None:
        group.attrs["clock_line_name"] = trace["clock_line_name"]
    group.attrs["sample_period"] = trace["sample_period"]
    group.attrs["t0"] = trace.get("t0", 0.0)
    group.attrs["timestamp_scale"] = trace.get("timestamp_scale", 1.0)
    group.attrs["align_to_first_timestamp"] = trace.get(
        "align_to_first_timestamp", False
    )
    if trace.get("timestamp_handle") is not None:
        group.attrs["timestamp_handle"] = trace["timestamp_handle"]


def read_result_metadata_attrs(group: h5py.Group) -> dict[str, Any]:
    """Read the metadata fields shared by `RESULTS/` and `RESULT_METADATA/` groups."""
    return {
        "handle": decode_optional_str_attr(group.attrs.get("handle")),
        "clock_line_name": decode_optional_str_attr(group.attrs.get("clock_line_name")),
        "sample_period": float(group.attrs.get("sample_period", 0.0)),
        "t0": float(group.attrs.get("t0", 0.0)),
        "timestamp_scale": float(group.attrs.get("timestamp_scale", 1.0)),
        "align_to_first_timestamp": bool(
            group.attrs.get("align_to_first_timestamp", False)
        ),
        "timestamp_handle": decode_optional_str_attr(
            group.attrs.get("timestamp_handle")
        ),
    }


def write_result_entry(
    device_group: h5py.Group,
    trace: ResultWriteMetadata,
    raw_values: Any,
    raw_timestamps: Any | None = None,
    logger: SupportsWarning | None = None,
) -> None:
    """Write one named OPX/QM result entry into the device `RESULTS` group.

    Parameters:
    - `device_group`: HDF5 group for `devices/<device_name>`
    - `trace`: compile-time metadata recorded by `OPX.add_result_trace()`
    - `raw_values`: payload returned by `result_handles.get(handle).fetch_all()`
    - `raw_timestamps`: optional separately fetched timestamp payload

    The worker calls this after a shot completes. The function stores both the
    compile-time metadata and the raw runtime payload without assuming that the
    result is necessarily a 1D trace.
    """
    results_group = device_group.require_group(RESULTS_GROUP_NAME)
    _delete_if_present(results_group, trace["trace_name"])

    # Each named QUA result gets one top-level group containing both metadata
    # and the preserved payload(s).
    result_group = results_group.create_group(trace["trace_name"])
    write_result_metadata_attrs(result_group, trace)

    _write_value(result_group, "values", raw_values, logger=logger)
    if raw_timestamps is not None:
        _write_value(result_group, "timestamps", raw_timestamps, logger=logger)


def _read_result_metadata(result_group: h5py.Group, trace_name: str) -> ResultEntry:
    """Return the shared reader-side metadata dictionary for one result entry."""
    entry: ResultEntry = {
        "trace_name": trace_name,
        **read_result_metadata_attrs(result_group),
        "values": _read_value(result_group["values"]),
        "timestamps": _read_value(result_group["timestamps"])
        if "timestamps" in result_group
        else None,
    }  # ty: ignore[missing-typed-dict-key]
    return entry


def read_result_entry(device_group: h5py.Group, trace_name: str) -> ResultEntry | None:
    """Read one named result entry from HDF5 into a plain Python dictionary.

    The returned dictionary is the shared reader-side representation used by the
    Runviewer parser and Lyse example analysis. It contains both the preserved
    payload (`values`, optional `timestamps`) and the metadata needed for later
    trace interpretation.
    """
    results_group = device_group.get(RESULTS_GROUP_NAME)
    if results_group is None or trace_name not in results_group:
        return None

    result_group = results_group[trace_name]
    # Return a plain Python dictionary so reader-side code does not need to know
    # anything about the HDF5 layout details.
    return _read_result_metadata(result_group, trace_name)


def _coerce_numeric_array(value: Any) -> np.ndarray | None:
    """Try to coerce arbitrary input into a flat float array, else return None."""
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError):
        return None

    if array.ndim == 0:
        array = array.reshape(1)
    return array.reshape(-1)


def _squeeze_array(value: Any) -> Any:
    """Normalise array containers so downstream walkers see simpler shapes."""
    if isinstance(value, np.ndarray):
        return np.squeeze(value)
    return value


def _positive_diffs(values: np.ndarray) -> np.ndarray:
    """Return strictly positive first differences from a numeric vector."""
    diffs = np.diff(values)
    return diffs[diffs > 0]


def _first_matching_field(
    field_names: dict[str, str], candidates: Sequence[str]
) -> str | None:
    """Return the first matching field name from a lowercase lookup table."""
    for candidate in candidates:
        if candidate in field_names:
            return field_names[candidate]
    return None


def _coerce_timestamped_segment(
    timestamp_values: Any, data_values: Any, allow_empty: bool = False
) -> TraceArrays | None:
    """Coerce timestamp/value arrays and validate that their shapes agree."""
    timestamps = _coerce_numeric_array(timestamp_values)
    values = _coerce_numeric_array(data_values)
    if timestamps is None or values is None:
        return None
    if timestamps.size != values.size:
        return None
    if not allow_empty and timestamps.size == 0:
        return None
    return timestamps, values


def _iter_numeric_leaf_arrays(value: Any) -> Iterator[np.ndarray]:
    """Yield 1D numeric arrays from nested payload structures."""
    value = _squeeze_array(value)

    if isinstance(value, np.ndarray):
        if value.dtype == object:
            if value.ndim == 0:
                yield from _iter_numeric_leaf_arrays(np.ravel(value)[0])
            else:
                for item in np.ravel(value):
                    yield from _iter_numeric_leaf_arrays(item)
            return

        yield np.asarray(value, dtype=np.float64).reshape(-1)
        return

    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_numeric_leaf_arrays(item)
        return

    yield np.asarray([value], dtype=np.float64)


def _extract_flat_values(raw_values: Any) -> np.ndarray:
    """Flatten nested value containers into a single numeric vector.

    This is used for result forms that semantically represent one list of values
    or timestamps even if QM returned them nested or wrapped in object arrays.
    """
    values = _coerce_numeric_array(raw_values)
    if values is not None:
        return values

    parts: list[np.ndarray] = [
        part for part in _iter_numeric_leaf_arrays(raw_values) if part.size
    ]
    if not parts:
        return np.asarray([], dtype=np.float64)
    return np.concatenate(parts)


def _segment_from_structured_array(value: np.ndarray) -> TraceArrays | None:
    """Return a timestamped segment from a structured array when recognised."""
    if not value.dtype.names:
        return None

    field_names: dict[str, str] = {name.lower(): name for name in value.dtype.names}
    timestamp_field = _first_matching_field(field_names, TIMESTAMP_FIELD_CANDIDATES)
    value_field = _first_matching_field(field_names, VALUE_FIELD_CANDIDATES)
    if timestamp_field is None or value_field is None:
        return None

    return _coerce_timestamped_segment(
        value[timestamp_field], value[value_field], allow_empty=True
    )


def _segment_from_timestamp_value_pair(value: Any) -> TraceArrays | None:
    """Return a segment for the explicit `(timestamps, values)` convention."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    return _coerce_timestamped_segment(value[0], value[1], allow_empty=False)


def _iter_timestamped_segments(value: Any) -> Iterator[TraceArrays]:
    """Yield `(timestamps, values)` segments found inside nested payloads."""
    value = _squeeze_array(value)

    if isinstance(value, np.ndarray):
        segment = _segment_from_structured_array(value)
        if segment is not None:
            yield segment
            return

        if value.dtype == object:
            if value.ndim == 0:
                yield from _iter_timestamped_segments(np.ravel(value)[0])
            else:
                for item in np.ravel(value):
                    yield from _iter_timestamped_segments(item)
        return

    segment = _segment_from_timestamp_value_pair(value)
    if segment is not None:
        yield segment
        return

    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_timestamped_segments(item)


def _extract_timestamped_segments(raw_values: Any) -> TraceSegments:
    """Extract `(timestamps, values)` bursts from timestamp-carrying payloads.

    The decoder recognises a few common timestamped result forms:

    - structured arrays with timestamp/value fields
    - nested pairs of `(timestamps, values)`
    - object arrays containing either of the above

    The output is a uniform list of numeric segments for later trace assembly.
    """
    return list(_iter_timestamped_segments(raw_values))


def _segment_timestamped_trace(
    timestamps: np.ndarray, values: np.ndarray
) -> TraceSegments:
    """Split a timestamped trace into contiguous bursts separated by large gaps."""
    positive_diffs = _positive_diffs(timestamps)
    if positive_diffs.size == 0:
        return [(timestamps, values)]

    # Estimate the "normal" sample spacing from the positive timestamp
    # differences, then split whenever we see a much larger jump.
    nominal_dt = np.median(positive_diffs)
    split_threshold = nominal_dt * 10.0
    split_indices = np.where(np.diff(timestamps) > split_threshold)[0] + 1
    timestamp_chunks = np.split(timestamps, split_indices)
    value_chunks = np.split(values, split_indices)
    return [
        (timestamp_chunk, value_chunk)
        for timestamp_chunk, value_chunk in zip(timestamp_chunks, value_chunks)
        if timestamp_chunk.size
    ]


def _reference_timestamp(timestamps: Any) -> float | None:
    """Return the first finite timestamp to use as an alignment anchor."""
    timestamps = np.asarray(timestamps, dtype=np.float64).reshape(-1)
    finite_timestamps = timestamps[np.isfinite(timestamps)]
    if finite_timestamps.size == 0:
        return None
    return float(finite_timestamps[0])


def _times_from_timestamps(
    result_entry: ResultEntry,
    timestamps: Any,
    reference_timestamp: float | None = None,
) -> np.ndarray:
    """Convert raw QM timestamps into shot-time seconds.

    By default QM timestamps are treated as already referenced to `t=0` and we
    simply apply `timestamp_scale` plus `t0`.

    For externally triggered secondary OPX jobs, the device may be armed before
    the master shot starts. In that case QM timestamps are offset by an unknown
    arming lead time. When `align_to_first_timestamp` is set, we remove that
    per-shot offset by subtracting the first finite returned timestamp and using
    `t0` as the known labscript time of the first sample.
    """
    timestamps = np.asarray(timestamps, dtype=np.float64)
    if result_entry.get("align_to_first_timestamp", False):
        if reference_timestamp is None:
            reference_timestamp = _reference_timestamp(timestamps)
        if reference_timestamp is not None:
            timestamps = timestamps - reference_timestamp

    return result_entry["t0"] + timestamps * result_entry.get("timestamp_scale", 1.0)


def _empty_trace() -> TraceArrays:
    """Return an empty `(times, values)` pair with consistent dtypes."""
    return np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)


def _segment_sample_dt(times: np.ndarray, default: float) -> float:
    """Estimate a segment sample interval from positive time differences."""
    positive_diffs = _positive_diffs(times)
    if positive_diffs.size == 0:
        return default
    return float(np.median(positive_diffs))


def _append_gap_marker(
    time_parts: list[np.ndarray], value_parts: list[np.ndarray], gap_time: float
) -> None:
    """Append a NaN separator so downstream line plots visibly break."""
    time_parts.append(np.asarray([gap_time], dtype=np.float64))
    value_parts.append(np.asarray([np.nan], dtype=np.float64))


def _reconcile_split_values(
    values: np.ndarray, timestamps: np.ndarray, trace_name: str
) -> np.ndarray:
    """Align a value vector with a separately fetched timestamp vector.

    When tick and scalar QUA streams were accidentally reused across two
    ``qua.program()`` builds, QM could concatenate every ``save()`` payload into
    each value handle. Tick saves are constant ``1``; scalar saves carry the
    integration result. Recover by keeping the subset whose length matches the
    authoritative timestamp stream.
    """
    if values.size == timestamps.size:
        return values

    if values.size < timestamps.size:
        raise RuntimeError(
            f"Result '{trace_name}' returned {values.size} values but "
            f"{timestamps.size} timestamps."
        )

    tick_marker_mask = values == 1.0
    if int(tick_marker_mask.sum()) == timestamps.size:
        return np.ones(timestamps.size, dtype=np.float64)

    scalar_mask = ~tick_marker_mask
    scalar_values = values[scalar_mask]
    if scalar_values.size == timestamps.size:
        return scalar_values.astype(np.float64, copy=False)

    raise RuntimeError(
        f"Result '{trace_name}' returned {values.size} values but "
        f"{timestamps.size} timestamps."
    )


def _trace_from_split_timestamps(
    result_entry: ResultEntry, raw_values: Any, raw_timestamps: Any
) -> TraceArrays:
    """Build a trace when values and timestamps were fetched separately."""
    values = _extract_flat_values(raw_values)
    timestamps = _extract_flat_values(raw_timestamps)
    if values.size == 0 or timestamps.size == 0:
        return _empty_trace()
    values = _reconcile_split_values(
        values, timestamps, str(result_entry["trace_name"])
    )
    return _times_from_timestamps(result_entry, timestamps), values


def _trace_from_embedded_timestamps(
    result_entry: ResultEntry, raw_values: Any
) -> TraceArrays | None:
    """Build a trace when timestamps are embedded in the value payload."""
    segments: TraceSegments = [
        chunk
        for segment_timestamps, segment_values in _extract_timestamped_segments(
            raw_values
        )
        for chunk in _segment_timestamped_trace(segment_timestamps, segment_values)
    ]
    if not segments:
        return None

    time_parts: list[np.ndarray] = []
    value_parts: list[np.ndarray] = []
    first_reference_timestamp = _reference_timestamp(segments[0][0])

    for index, (segment_timestamps, segment_values) in enumerate(segments):
        segment_times = _times_from_timestamps(
            result_entry,
            segment_timestamps,
            reference_timestamp=first_reference_timestamp,
        )
        time_parts.append(segment_times)
        value_parts.append(segment_values)

        if segment_times.size == 0:
            continue

        gap_start_time = segment_times[-1] + _segment_sample_dt(
            segment_times, result_entry["sample_period"]
        )
        if index == len(segments) - 1:
            _append_gap_marker(time_parts, value_parts, gap_start_time)
            continue

        # Insert a NaN separator between non-contiguous bursts so line plots
        # show a visible break instead of connecting them.
        next_segment_start_time = _times_from_timestamps(
            result_entry,
            np.asarray([segments[index + 1][0][0]], dtype=np.float64),
            reference_timestamp=first_reference_timestamp,
        )[0]
        if gap_start_time < next_segment_start_time:
            _append_gap_marker(time_parts, value_parts, gap_start_time)

    return np.concatenate(time_parts), np.concatenate(value_parts)


def _trace_from_uniform_samples(
    result_entry: ResultEntry, raw_values: Any
) -> TraceArrays | None:
    """Build a trace for uniformly sampled 1D numeric arrays."""
    values = np.asarray(raw_values)
    if (
        values.dtype.kind == "O"
        or values.ndim != 1
        or result_entry["sample_period"] <= 0.0
    ):
        return None

    times = (
        result_entry["t0"]
        + np.arange(values.size, dtype=np.float64) * result_entry["sample_period"]
    )
    return times, values.astype(np.float64, copy=False)


def build_trace_arrays(result_entry: ResultEntry) -> TraceArrays | None:
    """Interpret one stored result entry as a 1D `(times, values)` trace.

    This function is intentionally conservative: it only returns a trace when
    the stored payload can be interpreted unambiguously as one.

    Supported forms include:

    - `values` + separate `timestamps`
    - structured timestamped arrays
    - 1D numeric arrays with a meaningful `sample_period`

    If the payload is a multidimensional dataset or otherwise not naturally a
    1D trace, the function returns `None` so higher-level analysis can inspect
    the raw stored data directly instead of forcing a lossy conversion.
    """
    raw_values = result_entry["values"]
    raw_timestamps = result_entry.get("timestamps")

    if raw_timestamps is not None:
        return _trace_from_split_timestamps(result_entry, raw_values, raw_timestamps)

    embedded_trace = _trace_from_embedded_timestamps(result_entry, raw_values)
    if embedded_trace is not None:
        return embedded_trace

    uniform_trace = _trace_from_uniform_samples(result_entry, raw_values)
    if uniform_trace is not None:
        return uniform_trace

    # Multidimensional arrays or non-numeric object payloads are kept as raw
    # datasets for analysis, but they are not forced into a lossy 1D trace.
    return None


def _flush_trace_segment(
    segments: TraceSegments, current_times: list[float], current_values: list[float]
) -> None:
    """Append the current finite segment to `segments` if it is non-empty."""
    if not current_times:
        return
    segments.append(
        (
            np.asarray(current_times, dtype=np.float64),
            np.asarray(current_values, dtype=np.float64),
        )
    )


def _split_finite_trace_segments(
    times: np.ndarray,
    values: np.ndarray,
    finite_mask: np.ndarray,
    split_threshold: float,
) -> TraceSegments:
    """Split a trace into finite contiguous segments for Runviewer display."""
    segments: TraceSegments = []
    current_times: list[float] = []
    current_values: list[float] = []
    previous_time: float | None = None

    for time_value, value_value, is_finite in zip(times, values, finite_mask):
        if not is_finite:
            _flush_trace_segment(segments, current_times, current_values)
            current_times = []
            current_values = []
            previous_time = None
            continue

        if (
            previous_time is not None
            and time_value - previous_time > split_threshold
            and current_times
        ):
            _flush_trace_segment(segments, current_times, current_values)
            current_times = []
            current_values = []

        current_times.append(time_value)
        current_values.append(value_value)
        previous_time = time_value

    _flush_trace_segment(segments, current_times, current_values)
    return segments


def prepare_trace_for_runviewer(
    times: Any, values: Any, baseline: float = 0.0
) -> TraceArrays:
    """Convert a trace into a Runviewer-friendly stepped display trace.

    Runviewer expects digital/analog-style traces that visibly return to a
    baseline between separated bursts. This helper inserts synthetic pre/post
    points around each contiguous finite segment so gaps in acquisition become
    visually obvious in the UI.
    """
    times = np.asarray(times, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)

    finite_mask = np.isfinite(times) & np.isfinite(values)
    if not finite_mask.any():
        return _empty_trace()

    finite_times = times[finite_mask]
    positive_diffs = _positive_diffs(finite_times)
    nominal_dt = positive_diffs.min() if positive_diffs.size else 1e-9
    split_threshold = nominal_dt * 1.5

    segments = _split_finite_trace_segments(times, values, finite_mask, split_threshold)

    display_times: list[np.ndarray] = []
    display_values: list[np.ndarray] = []
    last_time: float | None = None

    for segment_times, segment_values in segments:
        if segment_times.size == 0:
            continue

        segment_positive_diffs = _positive_diffs(segment_times)
        sample_dt = (
            segment_positive_diffs.min()
            if segment_times.size > 1 and segment_positive_diffs.size
            else nominal_dt
        )

        if last_time is None:
            # For the first burst, placing the synthetic baseline point a full
            # sample interval early makes Runviewer appear to start the trace too
            # soon (for example at 1.09 s instead of 1.10 s). Keep the point just
            # infinitesimally before the first real sample so the visible edge is
            # anchored at the true start time.
            pre_time = np.nextafter(segment_times[0], -np.inf)
        else:
            pre_time = segment_times[0] - sample_dt

        if last_time is not None and pre_time <= last_time:
            pre_time = np.nextafter(last_time, np.inf)

        # Add an explicit baseline point before and after each acquisition burst
        # so Runviewer shows a stepped return to baseline between segments.
        display_times.append(np.asarray([pre_time], dtype=np.float64))
        display_values.append(np.asarray([baseline], dtype=np.float64))
        display_times.append(segment_times)
        display_values.append(segment_values)

        post_time = segment_times[-1] + sample_dt
        if post_time <= segment_times[-1]:
            post_time = np.nextafter(segment_times[-1], np.inf)

        display_times.append(np.asarray([post_time], dtype=np.float64))
        display_values.append(np.asarray([baseline], dtype=np.float64))
        last_time = post_time

    return np.concatenate(display_times), np.concatenate(display_values)
