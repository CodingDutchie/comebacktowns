"""Historic districts: does a National Register district polygon lie within the place?"""

from __future__ import annotations

import json
from typing import Any

from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.validation import make_valid

from pipeline.transform import Context, MetricRow

SOURCE_ID = "nrhp"


def esri_polygon(geometry: dict[str, Any]) -> Any:
    rings = [Polygon(r) for r in geometry.get("rings", []) if len(r) >= 4]
    if not rings:
        return None
    geom = rings[0] if len(rings) == 1 else MultiPolygon(rings)
    return geom if geom.is_valid else make_valid(geom)


def place_geometries(ctx: Context) -> dict[str, Any]:
    key = ctx.key("tiger", "places_36.geojson")
    document = json.loads(ctx.store.get_bytes(key))
    return {f["properties"]["GEOID"]: shape(f["geometry"]) for f in document["features"]}


def nrhp_metrics(ctx: Context) -> list[MetricRow]:
    key = ctx.key(SOURCE_ID, "ny_districts_polygons.json")
    document = json.loads(ctx.store.get_bytes(key))
    districts = []
    for feature in document["features"]:
        geom = esri_polygon(feature.get("geometry") or {})
        if geom is not None:
            districts.append(geom)
    places = place_geometries(ctx)
    period = ctx.as_of_for(SOURCE_ID)[:4]
    rows: list[MetricRow] = []
    for town in ctx.towns:
        place = places[town.geoid]
        count = sum(1 for d in districts if d.intersects(place))
        for metric, value in (
            ("nrhp_district_count", count),
            ("has_nrhp_district", int(count > 0)),
        ):
            rows.append(
                MetricRow(
                    geoid=town.geoid,
                    metric=metric,
                    period=period,
                    value=value,
                    source_id=SOURCE_ID,
                    as_of=ctx.as_of_for(SOURCE_ID),
                    r2_key=key,
                )
            )
    return rows
