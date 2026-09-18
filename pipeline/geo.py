"""Small geodesy helpers shared by ingest and transform."""

from __future__ import annotations

import math

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def nearest(
    lat: float,
    lon: float,
    points: list[dict],
    n: int = 1,
    key_lat: str = "lat",
    key_lon: str = "lon",
) -> list[tuple[float, dict]]:
    """The ``n`` closest points by straight-line miles, nearest first."""
    ranked = sorted(
        ((haversine_miles(lat, lon, p[key_lat], p[key_lon]), p) for p in points),
        key=lambda t: t[0],
    )
    return ranked[:n]
