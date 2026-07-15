"""Load seed data from JSON files into Pydantic models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import (
    DataSource,
    FlexSignal,
    FlexZone,
    MarketRule,
    PortalDataset,
    Portfolio,
)

SEED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "seed"


def _load_json(filename: str) -> list[dict[str, Any]]:
    path = SEED_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_data_sources() -> list[DataSource]:
    return [DataSource(**item) for item in _load_json("data_sources.json")]


def load_market_rules() -> list[MarketRule]:
    return [MarketRule(**item) for item in _load_json("market_rules.json")]


def load_flex_signals() -> list[FlexSignal]:
    return [FlexSignal(**item) for item in _load_json("flex_signals.json")]


def load_example_portfolios() -> list[Portfolio]:
    return [Portfolio(**item) for item in _load_json("example_portfolios.json")]


def load_flex_zones() -> list[FlexZone]:
    """Load v0.1 zone definitions from seed data."""
    return [FlexZone(**item) for item in _load_json("flex_zones.json")]


def load_portal_datasets() -> list[PortalDataset]:
    """Load v0.1 portal dataset metadata from seed data."""
    return [PortalDataset(**item) for item in _load_json("portal_datasets.json")]
