"""FlexCompass configuration — no hardcoded URLs or magic numbers.

All settings load from environment variables with sane defaults.
Import `config` from this module for a singleton instance.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app.catalogue_models import CATALOGUE_PORTALS, CataloguePortalConfig

__all__ = ["CATALOGUE_PORTALS", "CataloguePortalConfig", "config"]

# Load .env early so local public-portal settings are available.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class PortalConfig:
    """Per-portal connection settings."""
    base_url: str
    api_url: str | None = None
    rate_limit_rps: float = 2.0  # requests per second
    timeout_seconds: int = 30
    max_retries: int = 3
    cache_ttl_hours: int = 24
    max_pages: int = 1000


@dataclass(frozen=True)
class FlexCompassConfig:
    """Top-level configuration — all values overridable via env vars."""

    # --- Paths ---
    db_path: Path = field(default_factory=lambda: Path(
        os.environ.get("FLEXCOMPASS_DB_PATH",
            str(Path(__file__).resolve().parent.parent.parent / "data" / "flexcompass.db"))
    ))
    seed_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("FLEXCOMPASS_SEED_DIR",
            str(Path(__file__).resolve().parent.parent.parent / "data" / "seed"))
    ))
    cache_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("FLEXCOMPASS_CACHE_DIR",
            str(Path(__file__).resolve().parent.parent.parent / "data" / "cache"))
    ))

    # --- Sampling ---
    default_seed: int = field(default_factory=lambda: int(
        os.environ.get("FLEXCOMPASS_SEED", "42")
    ))

    # --- API ---
    api_host: str = field(default_factory=lambda: os.environ.get("FLEXCOMPASS_HOST", "127.0.0.1"))
    api_port: int = field(default_factory=lambda: int(os.environ.get("FLEXCOMPASS_PORT", "8099")))
    cors_origins: list[str] = field(default_factory=lambda: ["*"])

    # --- Capacity formula ---
    capacity_method_version: str = "v0.1"
    default_availability_pct: float = 0.03
    default_reliability_pct: float = 0.85

    # --- Portal configs ---
    portals: dict[str, PortalConfig] = field(default_factory=lambda: {
        "nged": PortalConfig(
            base_url="https://connecteddata.nationalgrid.co.uk",
            api_url="https://connecteddata.nationalgrid.co.uk/api/v2/catalog/datasets",
            rate_limit_rps=2.0,
            timeout_seconds=30,
        ),
        "nged_params": PortalConfig(
            base_url="https://dataportal2.westernpower.co.uk",
            rate_limit_rps=1.0,
            timeout_seconds=30,
        ),
        "spen": PortalConfig(
            base_url="https://spenergynetworks.opendatasoft.com",
            api_url="https://spenergynetworks.opendatasoft.com/api/v2/catalog/datasets",
            rate_limit_rps=2.0,
        ),
        "enwl": PortalConfig(
            base_url="https://electricitynorthwest.opendatasoft.com",
            api_url="https://electricitynorthwest.opendatasoft.com/api/v2/catalog/datasets",
            rate_limit_rps=2.0,
        ),
        "ssen": PortalConfig(
            base_url="https://data.ssen.co.uk",
            api_url="https://data.ssen.co.uk/api/3/action",
            rate_limit_rps=1.0,  # CKAN — be more conservative
        ),
    })

    # --- Confidence rubric thresholds ---
    confidence_polygon_field_count: int = 3   # fields needed for high confidence
    confidence_prefix_field_count: int = 2    # fields needed for medium
    confidence_min_fields_for_low: int = 1    # minimum fields for low (else insufficient_evidence)

    # --- Auth ---
    admin_token: str = field(default_factory=lambda: os.environ.get("FLEXCOMPASS_ADMIN_TOKEN", ""))

    def portal(self, name: str) -> PortalConfig:
        """Get portal config by name, raising KeyError if not found."""
        if name not in self.portals:
            raise KeyError(f"Unknown portal: {name}. Available: {list(self.portals.keys())}")
        return self.portals[name]


# Singleton — import this
config = FlexCompassConfig()
