"""Postcode→zone resolver for FlexCompass.

Resolution strategy (in priority order):
  1. Point-in-polygon: if zone has GeoJSON geometry and postcode has lat/lon
  2. Full-postcode match: if zone has explicit postcode lists
  3. Prefix match: zone postcode_prefixes against postcode district
  4. No match: returns empty list

Each match includes a confidence level based on the match quality.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from shapely.geometry import Point, shape

from .confidence import GeographyMatch
from .models import ConfidenceLevel, FlexZone

# UK postcode pattern: outward code (area + district) + inward code
# e.g. "B1 2AB", "SW1A 1AA", "CF10 3AQ"
_UK_POSTCODE_RE = re.compile(
    r"^([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})$", re.IGNORECASE
)


@dataclass
class PostcodeMatch:
    """A resolved match between a postcode and a zone."""
    zone_id: str
    zone: FlexZone
    match_type: GeographyMatch
    confidence: ConfidenceLevel
    postcode: str
    outward_code: str  # e.g. "B1"
    area: str          # e.g. "B"
    district: str      # e.g. "B1"


def parse_postcode(postcode: str) -> tuple[str, str, str] | None:
    """Parse a UK postcode into (full, outward_code, area).

    Returns None if the postcode is invalid.
    Examples:
        "B1 2AB"   → ("B1 2AB", "B1", "B")
        "SW1A 1AA" → ("SW1A 1AA", "SW1A", "SW")
    """
    cleaned = postcode.strip().upper()
    m = _UK_POSTCODE_RE.match(cleaned)
    if not m:
        return None
    outward = m.group(1).upper()
    # Area is the leading alpha prefix before any digit
    area = ""
    for c in outward:
        if c.isalpha():
            area += c
        else:
            break
    full = f"{outward} {m.group(2).upper()}"
    return full, outward, area


def _extract_prefix(postcode: str) -> str | None:
    """Extract the area prefix from a postcode (e.g. 'B' from 'B1 2AB')."""
    parsed = parse_postcode(postcode)
    if parsed is None:
        return None
    return parsed[2]  # area


def resolve_postcode(
    postcode: str,
    zones: list[FlexZone],
    postcode_coords: dict[str, tuple[float, float]] | None = None,
) -> list[PostcodeMatch]:
    """Resolve a postcode to matching zones.

    Args:
        postcode: UK postcode (e.g. "B1 2AB")
        zones: List of FlexZone objects to search
        postcode_coords: Optional dict of postcode → (lat, lon) for polygon matching

    Returns:
        List of PostcodeMatch, sorted by match quality (best first).
    """
    parsed = parse_postcode(postcode)
    if parsed is None:
        return []

    full, outward, area = parsed
    matches: list[PostcodeMatch] = []

    for zone in zones:
        match = _match_zone(full, outward, area, zone, postcode_coords)
        if match is not None:
            matches.append(match)

    # Sort: POLYGON > FULL_POSTCODE > PREFIX
    matches.sort(key=lambda m: m.match_type, reverse=True)
    return matches


def _match_zone(
    full: str,
    outward: str,
    area: str,
    zone: FlexZone,
    coords: dict[str, tuple[float, float]] | None,
) -> PostcodeMatch | None:
    """Try to match a postcode against a single zone."""
    # Pre-compute uppercase postcodes set for O(1) lookups
    upper_postcodes = {p.upper() for p in zone.postcodes}

    # Strategy 1: Point-in-polygon
    if zone.geometry and coords and full in coords:
        try:
            polygon = shape(zone.geometry)
            lat, lon = coords[full]
            point = Point(lon, lat)  # GeoJSON is (lon, lat)
            if polygon.contains(point):
                return PostcodeMatch(
                    zone_id=zone.zone_id,
                    zone=zone,
                    match_type=GeographyMatch.POLYGON,
                    confidence=ConfidenceLevel.high,
                    postcode=full,
                    outward_code=outward,
                    area=area,
                    district=outward,
                )
        except Exception:
            pass  # Geometry parsing failed, fall through

    # Strategy 2: Full postcode in zone postcode list
    if full.upper() in upper_postcodes:
        return PostcodeMatch(
            zone_id=zone.zone_id,
            zone=zone,
            match_type=GeographyMatch.FULL_POSTCODE,
            confidence=ConfidenceLevel.high,
            postcode=full,
            outward_code=outward,
            area=area,
            district=outward,
        )

    # Strategy 3: Outward code in zone postcode list
    if outward.upper() in upper_postcodes:
        return PostcodeMatch(
            zone_id=zone.zone_id,
            zone=zone,
            match_type=GeographyMatch.FULL_POSTCODE,
            confidence=ConfidenceLevel.medium,
            postcode=full,
            outward_code=outward,
            area=area,
            district=outward,
        )

    # Strategy 4: Prefix match
    zone_prefixes = {p.upper() for p in zone.postcode_prefixes}
    if area.upper() in zone_prefixes:
        return PostcodeMatch(
            zone_id=zone.zone_id,
            zone=zone,
            match_type=GeographyMatch.PREFIX,
            confidence=ConfidenceLevel.medium,
            postcode=full,
            outward_code=outward,
            area=area,
            district=outward,
        )

    return None


def resolve_postcode_to_dso(
    postcode: str,
    zones: list[FlexZone],
) -> dict[str, list[PostcodeMatch]]:
    """Resolve a postcode, grouped by DSO.

    Returns dict of dso_name → list of matches for that DSO.
    """
    matches = resolve_postcode(postcode, zones)
    by_dso: dict[str, list[PostcodeMatch]] = {}
    for m in matches:
        by_dso.setdefault(m.zone.dso, []).append(m)
    return by_dso


def batch_resolve(
    postcodes: list[str],
    zones: list[FlexZone],
) -> dict[str, list[PostcodeMatch]]:
    """Resolve multiple postcodes at once.

    Returns dict of postcode → matches.
    """
    return {pc: resolve_postcode(pc, zones) for pc in postcodes}
