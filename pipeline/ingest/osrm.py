"""Drive times from every town to New York City, the regional hubs and nearby hospitals.

One OSRM ``table`` request per town, paced at the demo server's one request per second,
stored under ``raw/osrm/{as_of}/{geoid}.json`` and never refetched.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx

from pipeline.geo import nearest
from pipeline.http import get, make_client
from pipeline.ingest import hospitals as hospitals_feed
from pipeline.ingest.base import Throttle, normalise_as_of, put_json, source
from pipeline.ingest.hospitals import hospitals_from_csv
from pipeline.scope import Town, towns_from_store
from pipeline.settings import scope_config
from pipeline.storage import RawStore, raw_key, raw_store

log = logging.getLogger(__name__)

SOURCE_ID = "osrm"


def destinations_for(
    town: Town, scope: dict[str, Any], hospitals: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    dest = scope["destinations"]
    out: list[dict[str, Any]] = [
        {
            "kind": "nyc",
            "name": dest["nyc"]["name"],
            "lat": dest["nyc"]["lat"],
            "lon": dest["nyc"]["lon"],
        }
    ]
    for hub in dest["hubs"]:
        out.append({"kind": "hub", "name": hub["name"], "lat": hub["lat"], "lon": hub["lon"]})
    for miles, hospital in nearest(town.lat, town.lon, hospitals, int(dest["hospitals_nearest"])):
        out.append(
            {
                "kind": "hospital",
                "name": hospital["name"],
                "facility_id": hospital["facility_id"],
                "lat": hospital["lat"],
                "lon": hospital["lon"],
                "crow_miles": round(miles, 2),
            }
        )
    return out


def table_url(template: str, town: Town, destinations: list[dict[str, Any]]) -> str:
    coords = ";".join(
        [f"{town.lon:.6f},{town.lat:.6f}"]
        + [f"{d['lon']:.6f},{d['lat']:.6f}" for d in destinations]
    )
    return template.format(coords=coords)


def fetch(
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
    towns: list[Town] | None = None,
    hospitals: list[dict[str, Any]] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> list[str]:
    entry = source(SOURCE_ID)
    scope = scope_config()
    as_of_str = normalise_as_of(as_of)
    store = store or raw_store()
    towns = towns if towns is not None else towns_from_store(store, as_of_str)
    if hospitals is None:
        hospital_key = hospitals_feed.fetch(as_of_str, store=store)[0]
        hospitals = hospitals_from_csv(store.get_bytes(hospital_key))
    own_client = client is None
    client = client or make_client()
    throttle = (
        Throttle(float(entry["min_interval_seconds"]), sleep=sleep)
        if sleep
        else Throttle(float(entry["min_interval_seconds"]))
    )
    keys: list[str] = []
    try:
        for town in towns:
            key = raw_key(SOURCE_ID, as_of_str, f"{town.geoid}.json")
            keys.append(key)
            if store.exists(key):
                continue
            destinations = destinations_for(town, scope, hospitals)
            url = table_url(entry["url"], town, destinations)
            params = {
                "sources": "0",
                "destinations": ";".join(str(i + 1) for i in range(len(destinations))),
                "annotations": "duration,distance",
            }
            throttle.wait()
            payload = get(client, url, params=params).json()
            if payload.get("code") != "Ok":
                raise RuntimeError(
                    f"osrm: {town.slug}: {payload.get('code')} {payload.get('message')}"
                )
            durations = payload["durations"][0]
            distances = payload.get("distances", [[None] * len(destinations)])[0]
            document = {
                "geoid": town.geoid,
                "slug": town.slug,
                "origin": {"lat": town.lat, "lon": town.lon},
                "destinations": [
                    {**d, "duration_s": durations[i], "distance_m": distances[i]}
                    for i, d in enumerate(destinations)
                ],
            }
            put_json(store, key, document, url=url)
            log.info("osrm: stored %s", key)
    finally:
        if own_client:
            client.close()
    return keys
