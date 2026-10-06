"""OpenStreetMap businesses inside each place polygon, via Overpass.

One query per town using the TIGER polygon (simplified), paced politely, stored under
``raw/osm/{as_of}/{geoid}.json``; a rerun only fetches towns that are missing.

The public Overpass servers are shared and go through busy spells (504s, "Query timed
out" remarks). Each query is tried on the configured server, then on each ``fallback_urls``
entry; all of them serve the same OpenStreetMap database, so this is the same source on
another machine, never a different source. The server that answered is recorded in the
stored document and its sidecar.

The slow, flaky part of a refresh is these 148 queries, so a Cloudflare Workflow
(``worker/src/osm-workflow.ts``) runs them ahead of the scheduled GitHub run, one durable
step per town, and stores the same documents under the same keys. It reads the queries
from the manifest ``write_queries`` publishes (``raw/osm-queries/{as_of}/queries.json``),
so the polygon and query logic lives here only. ``fetch`` then finds the files present and
skips them, and fills any the Workflow missed.
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


def servers(entry: dict[str, Any]) -> list[str]:
    """The configured Overpass server first, then the fallbacks, without duplicates."""
    out: list[str] = []
    for url in [entry["url"], *entry.get("fallback_urls", [])]:
        if url not in out:
            out.append(url)
    return out


def busy_remark(remark: str) -> bool:
    """Overpass answers 200 with a ``remark`` when the server, not the query, gave up."""
    return "runtime error" in remark.lower()


def ask(
    client: httpx.Client,
    urls: list[str],
    query: str,
    slug: str,
    *,
    retries: int,
    backoff: float,
) -> tuple[dict[str, Any], str]:
    """POST ``query`` to each server in turn until one answers with elements.

    A retryable status or a transport error exhausts that server's retries and moves on;
    a non-retryable status (a malformed query) raises at once, since another server would
    say the same. Returns the payload and the URL that produced it.
    """
    last: Exception | None = None
    for url in urls:
        host = httpx.URL(url).host

        def post(q: str = query, u: str = url) -> httpx.Response:
            return client.post(u, data={"data": q})

        try:
            response = with_retry(
                post, retries=retries, backoff=backoff, describe=f"overpass {slug} @ {host}"
            )
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            last = exc
            log.warning("osm: %s: %s gave up (%s), trying the next server", slug, host, exc)
            continue
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        remark = str(payload.get("remark", ""))
        if "elements" not in payload or "error" in remark.lower():
            message = remark or "no elements in response"
            if busy_remark(remark):
                last = RuntimeError(f"osm: {slug}: {message}")
                log.warning("osm: %s: %s said %r, trying the next server", slug, host, message)
                continue
            raise RuntimeError(f"osm: {slug}: {message}")
        return payload, url
    raise RuntimeError(f"osm: {slug}: every Overpass server failed; last: {last}") from last


QUERIES_SOURCE_ID = "osm-queries"
QUERIES_FILENAME = "queries.json"


def town_queries(
    entry: dict[str, Any], towns: list[Town], polygons: dict[str, Any]
) -> list[dict[str, Any]]:
    """One ``{geoid, slug, polygon_parts, query}`` per town, from the TIGER polygons."""
    missing = [t.slug for t in towns if t.geoid not in polygons]
    if missing:
        raise RuntimeError(f"osm: no TIGER polygon for {missing}")
    out: list[dict[str, Any]] = []
    for town in towns:
        poly, parts = poly_string(polygons[town.geoid], float(entry["simplify_tolerance_deg"]))
        out.append(
            {
                "geoid": town.geoid,
                "slug": town.slug,
                "polygon_parts": parts,
                "query": build_query(entry["query"], poly),
            }
        )
    return out


def queries_manifest(
    entry: dict[str, Any], as_of: str, tiger_key: str, towns: list[Town], polygons: dict[str, Any]
) -> dict[str, Any]:
    """Everything the Workflow needs to run the queries: servers, pacing, and one query per
    town. Built here so the Worker carries no copy of the polygon or query logic."""
    return {
        "as_of": as_of,
        "tiger_key": tiger_key,
        "source_id": SOURCE_ID,
        "servers": servers(entry),
        "min_interval_seconds": float(entry["min_interval_seconds"]),
        "retries_per_server": int(entry.get("retries_per_server", 3)),
        "backoff_seconds": float(entry.get("backoff_seconds", 15.0)),
        "towns": town_queries(entry, towns, polygons),
    }


def write_queries(
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
    towns: list[Town] | None = None,
) -> str:
    """Publish the queries manifest for the Workflow under ``raw/osm-queries/{as_of}/``."""
    entry = source(SOURCE_ID)
    as_of_str = normalise_as_of(as_of)
    store = store or raw_store()
    towns = towns if towns is not None else towns_from_store(store, as_of_str)
    tiger_key = tiger.fetch(as_of_str, store=store, client=client)[0]
    polygons = place_polygons(store.get_bytes(tiger_key))
    manifest = queries_manifest(entry, as_of_str, tiger_key, towns, polygons)
    key = raw_key(QUERIES_SOURCE_ID, as_of_str, QUERIES_FILENAME)
    put_json(store, key, manifest, url=f"derived from {tiger_key}")
    log.info("osm: wrote %s (%d towns)", key, len(manifest["towns"]))
    return key


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
    planned = {q["geoid"]: q for q in town_queries(entry, towns, polygons)}
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
            plan = planned[town.geoid]
            query, parts = str(plan["query"]), int(plan["polygon_parts"])
            throttle.wait()
            payload, url = ask(
                client,
                servers(entry),
                query,
                town.slug,
                retries=int(entry.get("retries_per_server", 3)),
                backoff=float(entry.get("backoff_seconds", 15.0)),
            )
            document = {
                "geoid": town.geoid,
                "slug": town.slug,
                "polygon_parts": parts,
                "query": query,
                "server": url,
                "osm3s": payload.get("osm3s"),
                "elements": payload["elements"],
            }
            put_json(store, key, document, url=url)
            host = httpx.URL(url).host
            log.info("osm: stored %s (%d elements, %s)", key, len(payload["elements"]), host)
    finally:
        if own_client:
            client.close()
    return keys
