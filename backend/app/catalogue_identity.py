"""Canonical opaque public identifiers for catalogue datasets."""

from __future__ import annotations

import base64
import binascii
import json

from .catalogue_models import CATALOGUE_PORTAL_IDS

_MAX_DATASET_REF_LENGTH = 2048


def encode_dataset_ref(portal_id: str, source_dataset_id: str) -> str:
    """Encode a portal-scoped source identifier as compact URL-safe text."""
    if portal_id not in CATALOGUE_PORTAL_IDS:
        raise ValueError("unknown catalogue portal")
    if not isinstance(source_dataset_id, str) or not source_dataset_id:
        raise ValueError("source dataset identifier must be a non-empty string")
    payload = json.dumps(
        [portal_id, source_dataset_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    if len(encoded) > _MAX_DATASET_REF_LENGTH:
        raise ValueError("dataset reference exceeds maximum length")
    return encoded


def decode_dataset_ref(value: str) -> tuple[str, str]:
    """Decode only the exact canonical representation produced above."""
    if not isinstance(value, str) or not value or len(value) > _MAX_DATASET_REF_LENGTH:
        raise ValueError("invalid dataset reference")
    try:
        raw = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
        decoded = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid dataset reference") from exc
    if (
        not isinstance(decoded, list)
        or len(decoded) != 2
        or not all(isinstance(item, str) and item for item in decoded)
    ):
        raise ValueError("invalid dataset reference")
    portal_id, source_dataset_id = decoded
    if portal_id not in CATALOGUE_PORTAL_IDS:
        raise ValueError("invalid dataset reference")
    if encode_dataset_ref(portal_id, source_dataset_id) != value:
        raise ValueError("invalid dataset reference")
    return portal_id, source_dataset_id
