"""Load data from SQLite into Pydantic models — drop-in replacement for seed_loader.

Usage: import db_loader instead of seed_loader to read from the DB.
"""

from __future__ import annotations

import json
from typing import Any

from .db import get_connection
from .models import (
    DataSource,
    FlexSignal,
    FlexZone,
    MarketRule,
    PortalDataset,
    Portfolio,
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row)


def load_portal_datasets() -> list[PortalDataset]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM portal_datasets").fetchall()
    result = []
    for r in rows:
        d = _row_to_dict(r)
        d["fields"] = json.loads(d.pop("fields_json", "[]"))
        d["useful_for"] = json.loads(d.pop("useful_for_json", "[]"))
        d["limitations"] = json.loads(d.pop("limitations_json", "[]"))
        result.append(PortalDataset(**d))
    return result


def load_flex_zones() -> list[FlexZone]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM flex_zones").fetchall()
    result = []
    for r in rows:
        d = _row_to_dict(r)
        d["postcode_prefixes"] = json.loads(d.pop("postcode_prefixes_json", "[]"))
        d["postcodes"] = json.loads(d.pop("postcodes_json", "[]"))
        if d.get("geometry_json"):
            d["geometry"] = json.loads(d.pop("geometry_json"))
        else:
            d.pop("geometry_json", None)
            d["geometry"] = None
        if d.get("raw_record_json"):
            d["raw_record"] = json.loads(d.pop("raw_record_json"))
        else:
            d.pop("raw_record_json", None)
            d["raw_record"] = None
        result.append(FlexZone(**d))
    return result


def load_flex_signals() -> list[FlexSignal]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM flex_signals").fetchall()
    result = []
    for r in rows:
        d = _row_to_dict(r)
        d["eligible_asset_types"] = json.loads(d.pop("eligible_asset_types_json", "[]"))
        d["missing_fields"] = json.loads(d.pop("missing_fields_json", "[]"))
        d["data_quality_notes"] = json.loads(d.pop("data_quality_notes_json", "[]"))
        if d.get("raw_record_json"):
            d["raw_record"] = json.loads(d.pop("raw_record_json"))
        else:
            d.pop("raw_record_json", None)
            d["raw_record"] = None
        result.append(FlexSignal(**d))
    return result


def load_data_sources() -> list[DataSource]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM data_sources").fetchall()
    result = []
    for r in rows:
        d = _row_to_dict(r)
        d["data_quality_notes"] = json.loads(d.pop("data_quality_notes_json", "[]"))
        d["limitations"] = json.loads(d.pop("limitations_json", "[]"))
        result.append(DataSource(**d))
    return result


def load_market_rules() -> list[MarketRule]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM market_rules").fetchall()
    result = []
    for r in rows:
        d = _row_to_dict(r)
        d["eligible_provider_types"] = json.loads(d.pop("eligible_provider_types_json", "[]"))
        d["eligible_asset_types"] = json.loads(d.pop("eligible_asset_types_json", "[]"))
        result.append(MarketRule(**d))
    return result


def load_example_portfolios() -> list[Portfolio]:
    """Portfolios are still in JSON seed — no DB table yet."""
    from .seed_loader import load_example_portfolios as _load
    return _load()
