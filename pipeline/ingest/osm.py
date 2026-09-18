"""OpenStreetMap businesses inside each place polygon, via Overpass.

One query per town using the TIGER polygon (simplified), paced politely, stored under
``raw/osm/{as_of}/{geoid}.json``; a rerun only fetches towns that are missing.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
from shapely.geometry import MultiPolygon, Polygon, shape

from pipeline.http import make_client, with_retry
from pipeline.ingest import tiger
from pipeline.ingest.base import Throttle, normalise_as_of, put_json, source
from pipeline.scope import Town, towns_from_store
from pipeline.storage import RawStore, raw_key, raw_store

log = logging.getLogger(__name__)

SOURCE_ID = "osm"


def place_polygons(geojson: bytes) -> dict[str, Any]:
    """GEOID -> shapely geometry from the TIGERweb places GeoJSON."""
    document = json.loads(geojson)
    return {f["properties"]["GEOID"]: shape(f["geometry"]) for f in document["features"]}


def poly_string(geom: Any, tolerance: float) -> tuple[str, int]:
    """Overpass ``poly:`` string ("lat lon lat lon ...") of the largest simplified polygon."""
    if isinstance(geom, MultiPolygon):
        parts = list(geom.geoms)
        polygon = max(parts, key=lambda p: p.area)
    elif isinstance(geom, Polygon):
        parts, polygon = [geom], geom
    else:
        raise TypeError(f"unsupported geometry {geom.geom_type}")
    simplified = polygon.simplify(tolerance, preserve_topology=True)
    coords = list(simplified.exterior.coords)
    return " ".join(f"{lat:.5f} {lon:.5f}" for lon, lat in coords), len(parts)


def build_query(template: str, poly: str) -> str:
    return template.replace("{poly}", poly)


def fetch(
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
    towns: list[Town] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> list[str]:
    entry = source(SOURCE_ID)
    as_of_str = normalise_as_of(as_of)
    store = store or raw_store()
    towns = towns if towns is not None else towns_from_store(store, as_of_str)
    tiger_key = tiger.fetch(as_of_str, store=store, client=client)[0]
    polygons = place_polygons(store.get_bytes(tiger_key))
    missing = [t.slug for t in towns if t.geoid not in polygons]
    if missing:
        raise RuntimeError(f"osm: no TIGER polygon for {missing}")
    own_client = client is None
    client = client or make_client(timeout=httpx.Timeout(180.0, connect=30.0))
    interval = float(entry["min_interval_seconds"])
    throttle = Throttle(interval, sleep=sleep) if sleep else Throttle(interval)
    keys: list[str] = []
    try:
        for town in towns:
            key = raw_key(SOURCE_ID, as_of_str, f"{town.geoid}.json")
            keys.append(key)
            if store.exists(key):
                continue
            poly, parts = poly_string(polygons[town.geoid], float(entry["simplify_tolerance_deg"]))
            query = build_query(entry["query"], poly)
            throttle.wait()

            def post(q: str = query) -> httpx.Response:
                return client.post(entry["url"], data={"data": q})

            response = with_retry(post, retries=6, backoff=15.0, describe=f"overpass {town.slug}")
            response.raise_for_status()
            payload = response.json()
            remark = payload.get("remark", "")
            if "elements" not in payload or "error" in remark.lower():
                raise RuntimeError(f"osm: {town.slug}: {remark or 'no elements in response'}")
            document = {
                "geoid": town.geoid,
                "slug": town.slug,
                "polygon_parts": parts,
                "query": query,
                "osm3s": payload.get("osm3s"),
                "elements": payload["elements"],
            }
            put_json(store, key, document, url=entry["url"])
            log.info("osm: stored %s (%d elements)", key, len(payload["elements"]))
    finally:
        if own_client:
            client.close()
    return keys
