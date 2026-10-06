"""OSRM drive-time and Overpass feeds against a mock transport."""

from __future__ import annotations

import json

import httpx
import pytest

from pipeline.geo import haversine_miles, nearest
from pipeline.ingest import osm, osrm
from pipeline.ingest.base import source as real_source
from pipeline.scope import Town, build_towns
from pipeline.settings import scope_config
from pipeline.storage import LocalStore, read_meta

HOSPITALS = [
    {"facility_id": "1", "name": "Columbia Memorial", "lat": 42.2506, "lon": -73.7869},
    {"facility_id": "2", "name": "Albany Med", "lat": 42.6531, "lon": -73.7727},
    {"facility_id": "3", "name": "Far Away", "lat": 43.1, "lon": -75.2},
    {"facility_id": "4", "name": "Farther", "lat": 40.7, "lon": -73.9},
]


def catskill() -> Town:
    return Town(
        geoid="3613002",
        name="Catskill",
        legal_type="village",
        county="Greene",
        county_fips="039",
        region="Capital Region",
        lat=42.214901,
        lon=-73.858674,
        pop_latest=3723,
        pop_latest_year=2024,
        slug="catskill-ny",
    )


def test_haversine_and_nearest():
    assert abs(haversine_miles(42.2149, -73.8587, 40.7527, -73.9772) - 101.2) < 1.0
    picked = nearest(42.2149, -73.8587, HOSPITALS, 2)
    assert [h["name"] for _, h in picked] == ["Columbia Memorial", "Albany Med"]


def test_osrm_destinations_and_request(local_store: LocalStore):
    scope = scope_config()
    dests = osrm.destinations_for(catskill(), scope, HOSPITALS)
    kinds = [d["kind"] for d in dests]
    assert kinds == ["nyc"] + ["hub"] * len(scope["destinations"]["hubs"]) + ["hospital"] * 3
    assert dests[-3]["name"] == "Columbia Memorial" and dests[-3]["crow_miles"] < 5

    seen = []

    def handler(request):
        seen.append(request)
        n = len(request.url.params["destinations"].split(";"))
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "durations": [[600.0 * (i + 1) for i in range(n)]],
                "distances": [[1000.0 * (i + 1) for i in range(n)]],
            },
        )

    keys = osrm.fetch(
        "2026-09-18",
        store=local_store,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        towns=[catskill()],
        hospitals=HOSPITALS,
        sleep=lambda s: None,
    )
    assert keys == ["raw/osrm/2026-09-18/3613002.json"]
    req = seen[0]
    assert req.url.path.startswith("/table/v1/driving/-73.858674,42.214901;-73.977200,40.752700;")
    assert req.url.params["sources"] == "0" and req.url.params["annotations"] == "duration,distance"
    doc = json.loads(local_store.get_bytes(keys[0]))
    assert doc["destinations"][0] == {
        "kind": "nyc",
        "name": "New York City (Grand Central)",
        "lat": 40.7527,
        "lon": -73.9772,
        "duration_s": 600.0,
        "distance_m": 1000.0,
    }
    assert doc["destinations"][-1]["kind"] == "hospital" and doc["destinations"][-1][
        "duration_s"
    ] == 600.0 * len(dests)
    # rerun is a no-op
    osrm.fetch(
        "2026-09-18",
        store=local_store,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        towns=[catskill()],
        hospitals=HOSPITALS,
        sleep=lambda s: None,
    )
    assert len(seen) == 1


def test_osrm_error_code_raises(local_store: LocalStore):
    handler = lambda r: httpx.Response(200, json={"code": "NoRoute", "message": "x"})  # noqa: E731
    with pytest.raises(RuntimeError, match="NoRoute"):
        osrm.fetch(
            "2026-09-18",
            store=local_store,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            towns=[catskill()],
            hospitals=HOSPITALS,
            sleep=lambda s: None,
        )


SQUARE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"GEOID": "3613002", "NAME": "Catskill village"},
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    [
                        [
                            [-73.87, 42.20],
                            [-73.85, 42.20],
                            [-73.85, 42.23],
                            [-73.87, 42.23],
                            [-73.87, 42.20],
                        ]
                    ],
                    [[[-73.90, 42.30], [-73.899, 42.30], [-73.899, 42.301], [-73.90, 42.30]]],
                ],
            },
        }
    ],
}


def test_poly_string_takes_largest_part_and_simplifies():
    polygons = osm.place_polygons(json.dumps(SQUARE).encode())
    poly, parts = osm.poly_string(polygons["3613002"], 0.0005)
    assert parts == 2
    coords = poly.split()
    assert len(coords) == 10  # 5 vertices of the big square, lat lon pairs
    assert coords[0] == "42.20000" and coords[1] == "-73.87000"


def test_osm_fetch_posts_query_and_stores_elements(local_store: LocalStore):
    local_store.put_bytes("raw/tiger/2026-09-18/places_36.geojson", json.dumps(SQUARE).encode())
    posted = []

    def handler(request):
        posted.append(request.content.decode())
        return httpx.Response(
            200,
            json={
                "osm3s": {"timestamp_osm_base": "2026-09-01T00:00:00Z"},
                "elements": [{"type": "node", "id": 1, "tags": {"shop": "bakery"}}],
            },
        )

    keys = osm.fetch(
        "2026-09-18",
        store=local_store,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        towns=[catskill()],
        sleep=lambda s: None,
    )
    assert keys == ["raw/osm/2026-09-18/3613002.json"]
    assert "poly%3A%2242.20000+-73.87000" in posted[0] and "shop" in posted[0]
    doc = json.loads(local_store.get_bytes(keys[0]))
    assert doc["polygon_parts"] == 2 and doc["elements"][0]["tags"]["shop"] == "bakery"


OK_PAYLOAD = {
    "osm3s": {"timestamp_osm_base": "2026-09-01T00:00:00Z"},
    "elements": [{"type": "node", "id": 1, "tags": {"shop": "bakery"}}],
}


def test_osm_falls_back_to_the_next_server_on_504s(local_store: LocalStore, monkeypatch):
    local_store.put_bytes("raw/tiger/2026-09-18/places_36.geojson", json.dumps(SQUARE).encode())
    monkeypatch.setattr(
        "pipeline.ingest.osm.source",
        lambda _id: {
            **real_source("osm"),
            "url": "https://primary.test/api/interpreter",
            "fallback_urls": ["https://second.test/api/interpreter"],
            "retries_per_server": 2,
            "backoff_seconds": 0,
        },
    )
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.host == "primary.test":
            return httpx.Response(504)
        return httpx.Response(200, json=OK_PAYLOAD)

    keys = osm.fetch(
        "2026-09-18",
        store=local_store,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        towns=[catskill()],
        sleep=lambda s: None,
    )
    assert hosts == ["primary.test", "primary.test", "primary.test", "second.test"]
    doc = json.loads(local_store.get_bytes(keys[0]))
    assert doc["server"] == "https://second.test/api/interpreter"
    assert doc["elements"][0]["tags"]["shop"] == "bakery"


def test_osm_busy_remark_moves_to_the_next_server(local_store: LocalStore, monkeypatch):
    local_store.put_bytes("raw/tiger/2026-09-18/places_36.geojson", json.dumps(SQUARE).encode())
    monkeypatch.setattr(
        "pipeline.ingest.osm.source",
        lambda _id: {
            **real_source("osm"),
            "url": "https://primary.test/api/interpreter",
            "fallback_urls": ["https://second.test/api/interpreter"],
            "backoff_seconds": 0,
        },
    )

    def handler(request):
        if request.url.host == "primary.test":
            return httpx.Response(
                200, json={"remark": 'runtime error: Query timed out in "query"', "elements": []}
            )
        return httpx.Response(200, json=OK_PAYLOAD)

    keys = osm.fetch(
        "2026-09-18",
        store=local_store,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        towns=[catskill()],
        sleep=lambda s: None,
    )
    assert json.loads(local_store.get_bytes(keys[0]))["server"].startswith("https://second.test")


def test_osm_bad_query_does_not_try_other_servers(monkeypatch):
    monkeypatch.setattr(
        "pipeline.ingest.osm.source",
        lambda _id: {"url": "https://primary.test/x", "fallback_urls": ["https://second.test/x"]},
    )
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        return httpx.Response(400, text="parse error")

    with pytest.raises(httpx.HTTPStatusError):
        osm.ask(
            httpx.Client(transport=httpx.MockTransport(handler)),
            osm.servers(osm.source("osm")),
            "bad",
            "x",
            retries=0,
            backoff=0,
        )
    assert hosts == ["primary.test"]


def test_osm_servers_dedupes_and_keeps_order():
    assert osm.servers({"url": "a", "fallback_urls": ["b", "a", "c"]}) == ["a", "b", "c"]
    assert osm.servers({"url": "a"}) == ["a"]


def test_osm_runtime_error_remark_raises(local_store: LocalStore):
    local_store.put_bytes("raw/tiger/2026-09-18/places_36.geojson", json.dumps(SQUARE).encode())

    def handler(r):
        return httpx.Response(
            200, json={"remark": "runtime error: Query timed out", "elements": []}
        )

    with pytest.raises(RuntimeError, match="timed out"):
        osm.fetch(
            "2026-09-18",
            store=local_store,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            towns=[catskill()],
            sleep=lambda s: None,
        )
    # every server said the same, so the error names the remark and the run stops


def test_osm_missing_polygon_fails(local_store: LocalStore, popest_bytes, gazetteer_zip, scope):
    local_store.put_bytes("raw/tiger/2026-09-18/places_36.geojson", json.dumps(SQUARE).encode())
    towns = build_towns(popest_bytes, gazetteer_zip, scope)
    with pytest.raises(RuntimeError, match="kingston-ny"):
        osm.fetch(
            "2026-09-18",
            store=local_store,
            client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
            towns=towns,
            sleep=lambda s: None,
        )


def test_osm_queries_manifest_carries_the_same_query_fetch_would_send(local_store: LocalStore):
    local_store.put_bytes("raw/tiger/2026-09-18/places_36.geojson", json.dumps(SQUARE).encode())
    key = osm.write_queries("2026-09-18", store=local_store, towns=[catskill()])
    assert key == "raw/osm-queries/2026-09-18/queries.json"
    manifest = json.loads(local_store.get_bytes(key))
    assert manifest["as_of"] == "2026-09-18" and manifest["tiger_key"].endswith("places_36.geojson")
    assert manifest["servers"] == real_source("osm")["workflow_servers"]
    assert manifest["min_interval_seconds"] == 2.0
    [town] = manifest["towns"]
    assert town["geoid"] == "3613002" and town["polygon_parts"] == 2
    assert 'poly:"42.20000 -73.87000' in town["query"] and "shop" in town["query"]
    # the sidecar names what it was derived from
    assert "places_36.geojson" in read_meta(local_store, key)["url"]

    posted = []

    def handler(request):
        posted.append(request.content.decode())
        return httpx.Response(200, json=OK_PAYLOAD)

    osm.fetch(
        "2026-09-18",
        store=local_store,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        towns=[catskill()],
        sleep=lambda s: None,
    )
    from urllib.parse import parse_qs

    assert parse_qs(posted[0])["data"][0] == town["query"]
