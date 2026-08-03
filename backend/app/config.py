"""FlexCompass configuration with environment-backed settings."""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import idna

__all__ = ["config"]

# Load .env early so local public-portal settings are available.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


_CORS_ORIGIN_ERROR = "CORS origins must be absolute HTTP(S) origins"
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def _canonical_cors_host(hostname: str) -> str:
    if "%" in hostname:
        raise ValueError(_CORS_ORIGIN_ERROR)
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            canonical = idna.encode(
                hostname,
                uts46=True,
                transitional=False,
                std3_rules=True,
            ).decode("ascii").lower()
        except idna.IDNAError as exc:
            raise ValueError(_CORS_ORIGIN_ERROR) from exc
        labels = canonical.split(".")
        if (
            len(canonical) > 253
            or not labels
            or all(label.isdigit() for label in labels)
            or any(_DNS_LABEL.fullmatch(label) is None for label in labels)
        ):
            raise ValueError(_CORS_ORIGIN_ERROR)
        return canonical
    if isinstance(address, ipaddress.IPv6Address):
        return f"[{address.compressed}]"
    return str(address)


def _cors_origins_from_env(value: str | None) -> tuple[str, ...]:
    raw_values = (
        value.split(",")
        if value
        else ["http://127.0.0.1:3000", "http://localhost:3000"]
    )
    origins: list[str] = []
    for raw in raw_values:
        origin = raw.strip()
        if origin == "*":
            raise ValueError("CORS wildcard is prohibited")
        if any(
            character.isspace()
            or ord(character) < 32
            or ord(character) == 127
            for character in origin
        ):
            raise ValueError(_CORS_ORIGIN_ERROR)
        try:
            parsed = urlsplit(origin)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise ValueError(_CORS_ORIGIN_ERROR) from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError(_CORS_ORIGIN_ERROR)
        canonical_host = _canonical_cors_host(hostname)
        if parsed.netloc.startswith("[") and not canonical_host.startswith("["):
            raise ValueError(_CORS_ORIGIN_ERROR)
        default_port = (
            parsed.scheme == "http" and port == 80
        ) or (parsed.scheme == "https" and port == 443)
        authority = canonical_host
        if port is not None and not default_port:
            authority = f"{canonical_host}:{port}"
        normalised = f"{parsed.scheme}://{authority}"
        if normalised not in origins:
            origins.append(normalised)
    return tuple(origins)


@dataclass(frozen=True)
class FlexCompassConfig:
    """Top-level configuration with values overridable by environment."""

    db_path: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "FLEXCOMPASS_DB_PATH",
                str(
                    Path(__file__).resolve().parent.parent.parent
                    / "data"
                    / "flexcompass.db"
                ),
            )
        )
    )
    seed_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "FLEXCOMPASS_SEED_DIR",
                str(
                    Path(__file__).resolve().parent.parent.parent
                    / "data"
                    / "seed"
                ),
            )
        )
    )
    cache_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "FLEXCOMPASS_CACHE_DIR",
                str(
                    Path(__file__).resolve().parent.parent.parent
                    / "data"
                    / "cache"
                ),
            )
        )
    )
    outage_db_path: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "FLEXCOMPASS_OUTAGE_DB_PATH",
                "data/cache/outages/registry.sqlite3",
            )
        )
    )
    outage_snapshot_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "FLEXCOMPASS_OUTAGE_SNAPSHOT_DIR",
                "data/snapshots/outages",
            )
        )
    )

    default_seed: int = field(
        default_factory=lambda: int(os.environ.get("FLEXCOMPASS_SEED", "42"))
    )

    api_host: str = field(
        default_factory=lambda: os.environ.get(
            "FLEXCOMPASS_HOST", "127.0.0.1"
        )
    )
    api_port: int = field(
        default_factory=lambda: int(
            os.environ.get("FLEXCOMPASS_PORT", "8099")
        )
    )
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: _cors_origins_from_env(
            os.environ.get("FLEXCOMPASS_CORS_ORIGINS")
        )
    )

    capacity_method_version: str = "v0.1"
    default_availability_pct: float = 0.03
    default_reliability_pct: float = 0.85

    confidence_polygon_field_count: int = 3
    confidence_prefix_field_count: int = 2
    confidence_min_fields_for_low: int = 1


config = FlexCompassConfig()
