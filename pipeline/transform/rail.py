"""Straight-line miles from each place to the nearest passenger rail station."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import Any

import yaml

from pipeline.geo import nearest
from pipeline.transform import Context, MetricRow

SOURCE_ID = "rail"


def load_stations(ctx: Context) -> list[dict[str, Any]]:
    stations: list[dict[str, Any]] = []
    amtrak_key = ctx.key(SOURCE_ID, "amtrak_stations.json")
    for feature in json.loads(ctx.store.get_bytes(amtrak_key))["features"]:
        attrs = feature["attributes"]
        geom = feature.get("geometry") or {}
        lat, lon = attrs.get("lat") or geom.get("y"), attrs.get("lon") or geom.get("x")
        if lat is None or lon is None:
            continue
        stations.append(
            {
                "name": attrs.get("StationName", "").strip(),
                "operator": "Amtrak",
                "lat": float(lat),
                "lon": float(lon),
                "r2_key": amtrak_key,
            }
        )
    mnr_key = ctx.key(SOURCE_ID, "gtfsmnr.zip")
    with zipfile.ZipFile(io.BytesIO(ctx.store.get_bytes(mnr_key))) as zf:
        stops = csv.DictReader(io.TextIOWrapper(zf.open("stops.txt"), encoding="utf-8-sig"))
        for stop in stops:
            name = stop["stop_name"]
            if "Yard" in name or "Shop" in name or stop.get("parent_station"):
                continue
            stations.append(
                {
                    "name": name,
                    "operator": "Metro-North",
                    "lat": float(stop["stop_lat"]),
                    "lon": float(stop["stop_lon"]),
                    "r2_key": mnr_key,
                }
            )
    manual_key = ctx.key(SOURCE_ID, "manual_stations.yml")
    for stop in yaml.safe_load(ctx.store.get_bytes(manual_key))["stations"]:
        stations.append(
            {
                "name": stop["name"],
                "operator": "Metro-North (manual)",
                "lat": float(stop["lat"]),
                "lon": float(stop["lon"]),
                "r2_key": manual_key,
            }
        )
    return stations


def rail_metrics(ctx: Context) -> list[MetricRow]:
    stations = load_stations(ctx)
    period = ctx.as_of_for(SOURCE_ID)[:4]
    rows: list[MetricRow] = []
    for town in ctx.towns:
        miles, station = nearest(town.lat, town.lon, stations, 1)[0]
        rows.append(
            MetricRow(
                geoid=town.geoid,
                metric="miles_to_rail_station",
                period=period,
                value=round(miles, 2),
                source_id=SOURCE_ID,
                as_of=ctx.as_of_for(SOURCE_ID),
                r2_key=station["r2_key"],
            )
        )
    return rows
