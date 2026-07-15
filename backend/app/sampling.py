"""Deterministic sampling utilities for FlexCompass.

All random sampling uses a seeded RNG so results are reproducible.
Pass `--seed N` or set `FLEXCOMPASS_SEED=42` to control the seed.
"""

from __future__ import annotations

import random
from typing import Any, Sequence

from .config import config


def get_rng(seed: int | None = None) -> random.Random:
    """Return a seeded Random instance. Uses config.default_seed if seed is None."""
    return random.Random(seed if seed is not None else config.default_seed)


def sample_postcodes(
    postcodes: Sequence[str],
    n: int,
    seed: int | None = None,
) -> list[str]:
    """Sample N postcodes deterministically from a list."""
    rng = get_rng(seed)
    if n >= len(postcodes):
        return list(postcodes)
    return rng.sample(list(postcodes), n)


def sample_out_of_zone(
    known_postcodes: Sequence[str],
    all_postcodes: Sequence[str],
    n: int,
    seed: int | None = None,
) -> list[str]:
    """Sample N postcodes that are NOT in known_postcodes (negative path)."""
    rng = get_rng(seed)
    candidates = [p for p in all_postcodes if p not in set(known_postcodes)]
    if n >= len(candidates):
        return candidates
    return rng.sample(candidates, n)


def sample_zones(
    zones: Sequence[Any],
    n: int,
    seed: int | None = None,
) -> list[Any]:
    """Sample N zones deterministically."""
    rng = get_rng(seed)
    if n >= len(zones):
        return list(zones)
    return rng.sample(list(zones), n)


def shuffled(items: Sequence[Any], seed: int | None = None) -> list[Any]:
    """Return a deterministically shuffled copy of items."""
    rng = get_rng(seed)
    result = list(items)
    rng.shuffle(result)
    return result


def weighted_sample(
    items: Sequence[Any],
    weights: Sequence[float],
    n: int,
    seed: int | None = None,
) -> list[Any]:
    """Weighted sampling without replacement (deterministic)."""
    rng = get_rng(seed)
    if n >= len(items):
        return list(items)
    # Use cumulative weight approach for sampling without replacement
    remaining = list(items)
    remaining_weights = list(weights)
    result = []
    for _ in range(n):
        total = sum(remaining_weights)
        if total <= 0:
            break
        r = rng.random() * total
        cumulative = 0.0
        for i, w in enumerate(remaining_weights):
            cumulative += w
            if cumulative >= r:
                result.append(remaining[i])
                remaining.pop(i)
                remaining_weights.pop(i)
                break
    return result
