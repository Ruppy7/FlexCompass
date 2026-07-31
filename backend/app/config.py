"""FlexCompass configuration — no hardcoded URLs or magic numbers.

All settings load from environment variables with sane defaults.
Import `config` from this module for a singleton instance.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["config"]

# Load .env early so local public-portal settings are available.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


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

    # --- Confidence rubric thresholds ---
    confidence_polygon_field_count: int = 3   # fields needed for high confidence
    confidence_prefix_field_count: int = 2    # fields needed for medium
    confidence_min_fields_for_low: int = 1    # minimum fields for low (else insufficient_evidence)

    # --- Auth ---
    admin_token: str = field(default_factory=lambda: os.environ.get("FLEXCOMPASS_ADMIN_TOKEN", ""))

# Singleton — import this
config = FlexCompassConfig()
