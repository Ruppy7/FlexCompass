"""Bounded sanitisation for values crossing outage persistence surfaces."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote

from app.catalogue_sync import redact

MAX_PERSISTED_STRING_BYTES = 64 * 1024
MAX_STRUCTURED_VALUE_BYTES = 512 * 1024
MAX_DECODE_PASSES = 8
MAX_CONTAINER_DEPTH = 32
MAX_CONTAINER_ITEMS = 10_000
UNSAFE_VALUE_SENTINEL = "[REDACTED_UNSAFE_VALUE]"

_R2_HOSTNAME = re.compile(
    r"(?<![a-z0-9.-])83025b28472d6aa2bf5ae59f3724aa78"
    r"\.r2\.cloudflarestorage\.com(?::443)?"
    r"(?=[/:?#\s\"'<>]|$)",
    re.IGNORECASE,
)
_X_AMZ_FIELD = re.compile(
    r"(?<![a-z0-9_-])x-amz-[a-z0-9-]+"
    r"(?:\s*[:=]\s*[^&,\s}\])\"']+)?",
    re.IGNORECASE,
)
_UNSAFE_MAPPING_KEYS = {"signed_url", "redirect_url"}


class UnsafePersistenceValueError(ValueError):
    """A value cannot cross an exact-preservation persistence boundary."""


def _string_is_unsafe(value: str, *, key: bool = False) -> bool:
    current = value
    for decode_pass in range(MAX_DECODE_PASSES + 1):
        if _R2_HOSTNAME.search(current) or _X_AMZ_FIELD.search(current):
            return True
        if key and current.strip().casefold() in _UNSAFE_MAPPING_KEYS:
            return True
        decoded = unquote(current)
        if decoded == current:
            return False
        if decode_pass == MAX_DECODE_PASSES:
            return True
        current = decoded
    return True


def source_bytes_contain_unsafe_material(content: bytes) -> bool:
    """Scan a complete bounded source response without persisted-leaf limits."""
    return _string_is_unsafe(content.decode("latin-1"))


def _bounded_json_size(value: Any) -> int:
    encoder = json.JSONEncoder(
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    size = 0
    try:
        for chunk in encoder.iterencode(value):
            size += len(chunk.encode("utf-8"))
            if size > MAX_STRUCTURED_VALUE_BYTES:
                raise UnsafePersistenceValueError(
                    "value is unsafe for persistence"
                )
    except UnsafePersistenceValueError:
        raise
    except (OverflowError, RecursionError, TypeError, ValueError):
        raise UnsafePersistenceValueError(
            "value is unsafe for persistence"
        ) from None
    return size


def _validate_structure(value: Any) -> None:
    stack: list[tuple[Any, int, bool]] = [(value, 0, False)]
    active_container_ids: set[int] = set()
    container_items = 0
    is_structured = isinstance(value, (dict, list))

    while stack:
        current, depth, leaving = stack.pop()
        if leaving:
            active_container_ids.remove(id(current))
            continue
        if depth > MAX_CONTAINER_DEPTH:
            raise UnsafePersistenceValueError("value is unsafe for persistence")
        if isinstance(current, str):
            if len(current.encode("utf-8")) > MAX_PERSISTED_STRING_BYTES:
                raise UnsafePersistenceValueError(
                    "value is unsafe for persistence"
                )
            continue
        if current is None or isinstance(current, (bool, int)):
            continue
        if isinstance(current, float):
            if not math.isfinite(current):
                raise UnsafePersistenceValueError(
                    "value is unsafe for persistence"
                )
            continue
        if isinstance(current, dict):
            container_id = id(current)
            if container_id in active_container_ids:
                raise UnsafePersistenceValueError(
                    "value is unsafe for persistence"
                )
            active_container_ids.add(container_id)
            stack.append((current, depth, True))
            container_items += len(current)
            if container_items > MAX_CONTAINER_ITEMS:
                raise UnsafePersistenceValueError(
                    "value is unsafe for persistence"
                )
            for key, item in current.items():
                if not isinstance(key, str):
                    raise UnsafePersistenceValueError(
                        "value is unsafe for persistence"
                    )
                if len(key.encode("utf-8")) > MAX_PERSISTED_STRING_BYTES:
                    raise UnsafePersistenceValueError(
                        "value is unsafe for persistence"
                    )
                stack.append((item, depth + 1, False))
            continue
        if isinstance(current, list):
            container_id = id(current)
            if container_id in active_container_ids:
                raise UnsafePersistenceValueError(
                    "value is unsafe for persistence"
                )
            active_container_ids.add(container_id)
            stack.append((current, depth, True))
            container_items += len(current)
            if container_items > MAX_CONTAINER_ITEMS:
                raise UnsafePersistenceValueError(
                    "value is unsafe for persistence"
                )
            for item in current:
                stack.append((item, depth + 1, False))
            continue
        raise UnsafePersistenceValueError("value is unsafe for persistence")

    if is_structured:
        _bounded_json_size(value)


def _sanitise_validated(value: Any) -> Any:
    if isinstance(value, dict):
        safe_mapping: dict[str, Any] = {}
        for key, item in value.items():
            if _string_is_unsafe(key, key=True):
                continue
            safe_mapping[key] = _sanitise_validated(item)
        return safe_mapping
    if isinstance(value, list):
        return [_sanitise_validated(item) for item in value]
    if isinstance(value, str) and _string_is_unsafe(value):
        return UNSAFE_VALUE_SENTINEL
    return value


def sanitise_diagnostic_value(value: Any) -> Any:
    """Return bounded, redacted diagnostic data without reflecting unsafe input."""
    try:
        _validate_structure(value)
    except UnsafePersistenceValueError:
        return UNSAFE_VALUE_SENTINEL
    return redact(_sanitise_validated(value))


def require_exact_safe_structure(value: Any) -> None:
    """Reject a value whenever safe persistence would alter it."""
    _validate_structure(value)
    if sanitise_diagnostic_value(value) != value:
        raise UnsafePersistenceValueError("value is unsafe for persistence")


def require_exact_safe_raw_record(raw_record: Mapping[str, Any]) -> None:
    """Reject an unsafe raw record without returning or mutating it."""
    try:
        require_exact_safe_structure(raw_record)
    except UnsafePersistenceValueError:
        raise UnsafePersistenceValueError(
            "raw record is unsafe for persistence"
        ) from None
