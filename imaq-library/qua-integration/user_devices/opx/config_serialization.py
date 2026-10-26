"""JSON serialisation for QM configuration payloads stored in shot HDF5 files."""

from __future__ import annotations

import json
from typing import Any

FORMAT_NAME = "opx-qm-config-json"
FORMAT_VERSION = 1
DATASET_ATTR_SERIALIZATION = f"{FORMAT_NAME}-v{FORMAT_VERSION}"

_TAG = "__opx_type__"
_ITEMS = "items"
_VALUE = "value"


def _encode(value: Any) -> Any:
    """Convert a QM config value into JSON-compatible data preserving key types."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, tuple):
        return {_TAG: "tuple", _ITEMS: [_encode(item) for item in value]}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {
            _TAG: "dict",
            _ITEMS: [[_encode(key), _encode(item)] for key, item in value.items()],
        }
    raise TypeError(
        f"QM config contains unsupported value type {type(value).__name__}."
    )


def _decode(value: Any) -> Any:
    """Restore a value produced by :func:`_encode`."""
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if not isinstance(value, dict) or _TAG not in value:
        return value

    tag = value[_TAG]
    if tag == "tuple":
        return tuple(_decode(item) for item in value[_ITEMS])
    if tag == "dict":
        return {_decode(key): _decode(item) for key, item in value[_ITEMS]}
    raise ValueError(f"Unknown OPX QM config JSON tag {tag!r}.")


def qm_config_to_json_bytes(config: Any) -> bytes:
    """Serialise a QM config to deterministic UTF-8 JSON bytes."""
    payload = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        _VALUE: _encode(config),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def qm_config_from_json_bytes(data: bytes | bytearray | memoryview) -> Any:
    """Deserialize a QM config written by :func:`qm_config_to_json_bytes`."""
    payload = json.loads(bytes(data).decode("utf-8"))
    if payload.get("format") != FORMAT_NAME:
        raise ValueError("Unsupported OPX QM config JSON format.")
    if payload.get("version") != FORMAT_VERSION:
        raise ValueError(
            f"Unsupported OPX QM config JSON version {payload.get('version')!r}."
        )
    return _decode(payload[_VALUE])
