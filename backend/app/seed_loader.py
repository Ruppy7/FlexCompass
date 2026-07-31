"""Load the checked-in synthetic example portfolios."""

from __future__ import annotations

import json
from pathlib import Path

from .models import Portfolio

SEED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "seed"


def load_example_portfolios() -> list[Portfolio]:
    path = SEED_DIR / "example_portfolios.json"
    with path.open(encoding="utf-8") as seed_file:
        items = json.load(seed_file)
    return [Portfolio(**item) for item in items]
