"""Drive minutes from the OSRM table snapshots, plus the straight-line fallbacks.

The fallbacks are separate metrics (``crow_miles_*``) computed from coordinates alone, so a
routed figure is never silently replaced by a straight line.
"""

from __future__ import annotations

import json

from pipeline.geo import haversine_miles
from pipeline.settings import scope_config
from pipeline.transform import Context, MetricRow

SOURCE_ID = "osrm"
HOSPITAL_MINUTES = 20


def osrm_metrics(ctx: Context) -> list[MetricRow]:
    keys = set(ctx.keys(SOURCE_ID))
    period = ctx.as_of[:7]
    rows: list[MetricRow] = []
    for town in ctx.towns:
        key = f"raw/{SOURCE_ID}/{ctx.as_of}/{town.geoid}.json"
        if key not in keys:
            continue
        document = json.loads(ctx.store.get_bytes(key))
        by_kind: dict[str, list[float]] = {}
        for dest in document["destinations"]:
            if dest.get("duration_s") is not None:
                by_kind.setdefault(dest["kind"], []).append(dest["duration_s"] / 60)
        values: dict[str, float | None] = {
            "drive_min_nyc": min(by_kind["nyc"]) if by_kind.get("nyc") else None,
            "drive_min_regional_hub": min(by_kind["hub"]) if by_kind.get("hub") else None,
            "drive_min_nearest_hospital": min(by_kind["hospital"])
            if by_kind.get("hospital")
            else None,
        }
        hospital = values["drive_min_nearest_hospital"]
        values["hospital_within_20min"] = (
            None if hospital is None else float(hospital <= HOSPITAL_MINUTES)
        )
        for metric, value in values.items():
            rows.append(
                MetricRow(
                    geoid=town.geoid,
                    metric=metric,
                    period=period,
                    value=None if value is None else round(value, 1),
                    source_id=SOURCE_ID,
                    as_of=ctx.as_of,
                    r2_key=key,
                )
            )
    return rows


def crow_metrics(ctx: Context) -> list[MetricRow]:
    """Straight-line miles to NYC and the nearest hub, from Gazetteer coordinates."""
    dest = scope_config()["destinations"]
    key = ctx.keys("gazetteer")[0]
    period = ctx.as_of[:4]
    rows: list[MetricRow] = []
    for town in ctx.towns:
        nyc = haversine_miles(town.lat, town.lon, dest["nyc"]["lat"], dest["nyc"]["lon"])
        hub = min(haversine_miles(town.lat, town.lon, h["lat"], h["lon"]) for h in dest["hubs"])
        for metric, value in (("crow_miles_nyc", nyc), ("crow_miles_regional_hub", hub)):
            rows.append(
                MetricRow(
                    geoid=town.geoid,
                    metric=metric,
                    period=period,
                    value=round(value, 2),
                    source_id="gazetteer",
                    as_of=ctx.as_of,
                    r2_key=key,
                )
            )
    return rows
