"""Feed modules against a mock transport: request shape, pagination, idempotence."""

from __future__ import annotations

import io
import json
import zipfile

import httpx
import pytest

from pipeline.ingest import acs, dri, hospitals, irs, nrhp, permits, rail, tiger, zillow
from pipeline.ingest.base import Throttle, fetch_arcgis_layer
from pipeline.storage import LocalStore, read_meta


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def ok_json(payload):
    return httpx.Response(200, json=payload)


def test_throttle_spaces_calls():
    now = {"t": 0.0}
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        now["t"] += s

    t = Throttle(1.0, sleep=sleep, clock=lambda: now["t"])
    t.wait()
    now["t"] += 0.25
    t.wait()
    t.wait()
    assert sleeps == [0.75, 1.0]


def test_arcgis_pagination_merges_pages(local_store: LocalStore):
    calls = []

    def handler(request):
        calls.append(dict(request.url.params))
        offset = int(request.url.params["resultOffset"])
        if offset == 0:
            return ok_json(
                {
                    "fields": [{"name": "A"}],
                    "exceededTransferLimit": True,
                    "features": [{"attributes": {"A": 1}}, {"attributes": {"A": 2}}],
                }
            )
        return ok_json({"fields": [{"name": "A"}], "features": [{"attributes": {"A": 3}}]})

    key = fetch_arcgis_layer(
        "nrhp",
        "https://x/layer/0/query",
        where="1=1",
        filename="f.json",
        as_of="2026-09-18",
        page_size=2,
        store=local_store,
        client=client_for(handler),
    )
    doc = json.loads(local_store.get_bytes(key))
    assert [f["attributes"]["A"] for f in doc["features"]] == [1, 2, 3]
    assert "exceededTransferLimit" not in doc and doc["query"]["where"] == "1=1"
    assert [c["resultOffset"] for c in calls] == ["0", "2"]
    assert calls[0]["f"] == "json" and calls[0]["outSR"] == "4326"
    # second call is a no-op
    fetch_arcgis_layer(
        "nrhp",
        "https://x/layer/0/query",
        where="1=1",
        filename="f.json",
        as_of="2026-09-18",
        store=local_store,
        client=client_for(handler),
    )
    assert len(calls) == 2


def test_arcgis_error_body_raises(local_store: LocalStore):
    handler = lambda r: ok_json({"error": {"code": 400, "message": "bad"}})  # noqa: E731
    with pytest.raises(RuntimeError, match="bad"):
        fetch_arcgis_layer(
            "nrhp",
            "https://x/q",
            where="1=1",
            filename="f.json",
            as_of="2026-09-18",
            store=local_store,
            client=client_for(handler),
        )


def test_permits_fetches_each_configured_year(local_store: LocalStore):
    urls = []

    def handler(request):
        urls.append(str(request.url))
        if request.method == "HEAD":  # nothing published beyond the configured years
            return httpx.Response(404)
        return httpx.Response(200, content=b"Survey,State\nDate,Code\n\n2024,36\n")

    keys = permits.fetch("2026-09-18", store=local_store, client=client_for(handler))
    assert len(keys) == 5 and keys[-1] == "raw/permits/2026-09-18/ne2025a.txt"
    gets = [u for u in urls if not u.endswith("/ne2026a.txt")]
    assert gets[0].endswith("/ne2021a.txt") and "Northeast%20Region" in gets[0]
    heads = [u for u in urls if u.endswith("/ne2026a.txt")]
    assert len(heads) == 1  # probed once, then stopped at the first missing year


def test_permits_pulls_a_newly_published_year(local_store: LocalStore):
    def handler(request):
        year = int(request.url.path[-9:-5])
        if year > 2026:
            return httpx.Response(404)
        return httpx.Response(200, content=b"Survey,State\nDate,Code\n\n2024,36\n")

    assert permits.discover(client_for(handler)) == [2026]
    keys = permits.fetch("2026-09-18", store=local_store, client=client_for(handler))
    assert len(keys) == 6 and keys[-1] == "raw/permits/2026-09-18/ne2026a.txt"


def test_permits_discovery_does_not_mistake_an_outage_for_an_unreleased_year():
    def handler(request):
        return httpx.Response(500) if request.method == "HEAD" else httpx.Response(200)

    with pytest.raises(httpx.HTTPStatusError):
        permits.discover(httpx.Client(transport=httpx.MockTransport(handler)))


def test_nrhp_queries_both_layers_for_ny_districts(local_store: LocalStore):
    wheres = []

    def handler(request):
        wheres.append((request.url.path, request.url.params["where"]))
        return ok_json(
            {"features": [{"attributes": {"RESNAME": "X"}, "geometry": {"x": -73.9, "y": 42.2}}]}
        )

    keys = nrhp.fetch("2026-09-18", store=local_store, client=client_for(handler))
    assert keys == [
        "raw/nrhp/2026-09-18/ny_districts_points.json",
        "raw/nrhp/2026-09-18/ny_districts_polygons.json",
    ]
    assert [p for p, _ in wheres] == [
        "/arcgis/rest/services/cultural_resources/nrhp_locations/MapServer/0/query",
        "/arcgis/rest/services/cultural_resources/nrhp_locations/MapServer/1/query",
    ]
    assert all(w == "State='NEW YORK' AND ResType='district'" for _, w in wheres)


def test_tiger_requests_statewide_geojson(local_store: LocalStore):
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, content=b'{"type":"FeatureCollection","features":[]}')

    keys = tiger.fetch("2026-09-18", store=local_store, client=client_for(handler))
    assert keys == ["raw/tiger/2026-09-18/places_36.geojson"]
    assert seen["where"] == "STATE='36'" and seen["f"] == "geojson" and seen["outSR"] == "4326"


def test_rail_fetches_amtrak_trains_and_mnr_gtfs(local_store: LocalStore):
    def handler(request):
        if request.url.host == "services.arcgis.com":
            assert request.url.params["where"] == "StnType='TRAIN'"
            return ok_json(
                {
                    "features": [
                        {"attributes": {"StationName": "Hudson, NY", "lat": 42.25, "lon": -73.79}}
                    ]
                }
            )
        return httpx.Response(
            200, content=b"PK\x05\x06" + b"\0" * 18, headers={"Content-Type": "application/zip"}
        )

    keys = rail.fetch("2026-09-18", store=local_store, client=client_for(handler))
    assert keys == [
        "raw/rail/2026-09-18/amtrak_stations.json",
        "raw/rail/2026-09-18/gtfsmnr.zip",
        "raw/rail/2026-09-18/manual_stations.yml",
    ]
    assert read_meta(local_store, keys[1])["content_type"] == "application/zip"
    assert b"Port Jervis" in local_store.get_bytes(keys[2])
    assert read_meta(local_store, keys[2])["url"] == "repo://config/rail_stations_manual.yml"


def test_zillow_streams_both_files(local_store: LocalStore):
    names = []

    def handler(request):
        names.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, content=b"RegionID,RegionName\n1,Catskill\n")

    keys = zillow.fetch("2026-09-18", store=local_store, client=client_for(handler))
    assert keys == ["raw/zillow/2026-09-18/zhvi_city.csv", "raw/zillow/2026-09-18/zori_city.csv"]
    assert names[0].startswith("City_zhvi") and names[1].startswith("City_zori")


def test_hospitals_csv_filter():
    csv = (
        b"Facility ID,Facility Name,Description,Facility City,Facility County,Facility Latitude,Facility Longitude\n"
        b"1,Columbia Memorial,Hospital,Hudson,Columbia,42.25,-73.79\n"
        b"2,Some Clinic,Diagnostic and Treatment Center,Hudson,Columbia,42.2,-73.7\n"
        b"3,No Coords Hospital,Hospital,X,Y,,\n"
    )
    rows = hospitals.hospitals_from_csv(csv)
    assert [r["name"] for r in rows] == ["Columbia Memorial"] and rows[0]["lat"] == 42.25


def test_dri_discovers_round_pages_and_snapshots_html(local_store: LocalStore):
    pages = {
        "/programs/downtown-revitalization-initiative": '<a href=/downtown-revitalization-initiative/downtown-revitalization-initiative-round-nine>Round 9</a> <a href="/downtown-revitalization-initiative-round-one">one</a>',
        "/programs/ny-forward": '<a href="/ny-forward/ny-forward-round-two">two</a>',
        "/downtown-revitalization-initiative/downtown-revitalization-initiative-round-nine": "<h2>Capital Region</h2><p><strong>Hudson</strong></p>",
        "/downtown-revitalization-initiative-round-one": "<p>Capital Region – Glens Falls</p>",
        "/ny-forward/ny-forward-round-two": "<h2>Capital Region</h2><p><strong>Hoosick Falls</strong></p>",
    }
    hits = []

    def handler(request):
        hits.append(request.url.path)
        return httpx.Response(
            200, text=pages[request.url.path], headers={"Content-Type": "text/html"}
        )

    keys = dri.fetch("2026-09-18", store=local_store, client=client_for(handler))
    assert "raw/dri/2026-09-18/dri_downtown-revitalization-initiative-round-nine.html" in keys
    assert "raw/dri/2026-09-18/nyf_ny-forward-round-two.html" in keys
    manifest = json.loads(local_store.get_bytes("raw/dri/2026-09-18/manifest.json"))
    assert [p["kind"] for p in manifest["dri"]] == ["program", "round", "round"]
    assert read_meta(local_store, keys[0])["url"].endswith(
        "/programs/downtown-revitalization-initiative"
    )
    # rerun fetches nothing
    n = len(hits)
    dri.fetch("2026-09-18", store=local_store, client=client_for(handler))
    assert len(hits) == n


def test_acs_requires_key_and_never_stores_it(monkeypatch, local_store: LocalStore):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    with pytest.raises(Exception, match="CENSUS_API_KEY"):
        acs.fetch("2026-09-18", store=local_store, client=client_for(lambda r: ok_json([])))

    monkeypatch.setenv("CENSUS_API_KEY", "sekrit")
    seen = []

    def handler(request):
        seen.append(request)
        table = request.url.params["get"][6:-1]
        return ok_json(
            [
                ["NAME", f"{table}_001E", f"{table}_001M", "state", "place"],
                ["Catskill village, New York", "250000", "30000", "36", "13002"],
            ]
        )

    keys = acs.fetch(
        "2026-09-18", store=local_store, client=client_for(handler), sleep=lambda s: None
    )
    assert keys[0] == "raw/acs/2026-09-18/acs5_2024_B25077_place.json"
    assert all(r.url.params["key"] == "sekrit" for r in seen)
    place_requests = [r for r in seen if r.url.params["for"] == "place:*"]
    assert place_requests and all(r.url.params["in"] == "state:36" for r in place_requests)
    assert any("2019/acs/acs5" in str(r.url) for r in seen), "prior vintage fetched"
    assert not any(
        r.url.params["for"].startswith("metropolitan") and "2019" in str(r.url) for r in seen
    )
    for key in keys:
        assert b"sekrit" not in local_store.get_bytes(key)
        assert "sekrit" not in read_meta(local_store, key)["url"]
    doc = json.loads(local_store.get_bytes(keys[0]))
    assert doc[1][0] == "Catskill village, New York"


def test_acs_rejects_wrong_table(monkeypatch, local_store: LocalStore):
    monkeypatch.setenv("CENSUS_API_KEY", "k")
    handler = lambda r: ok_json([["NAME", "B99999_001E"], ["x", "1"]])  # noqa: E731
    with pytest.raises(RuntimeError, match="carries no B25077"):
        acs.fetch("2026-09-18", store=local_store, client=client_for(handler), sleep=lambda s: None)


def make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


IRS_ENTRY = {
    "url": "https://www.irs.gov/pub/irs-soi/county{flow}{years}.csv",
    "years": ["2122", "2223"],
    "flows": ["inflow", "outflow"],
    "discover_ahead": 2,
}


def test_irs_next_pair_rolls_the_filing_years():
    assert irs.next_pair("2223") == "2324"
    assert irs.next_pair("2021") == "2122"
    assert irs.next_pair("9899") == "9900"


def test_irs_pulls_a_new_pair_only_when_both_flows_exist(local_store: LocalStore, monkeypatch):
    monkeypatch.setattr("pipeline.ingest.irs.source", lambda _id: IRS_ENTRY)

    def handler(request):
        path = request.url.path
        if request.method == "HEAD":
            # 2324 is complete; 2425 has only its inflow file so far
            return httpx.Response(200 if "2324" in path or "inflow2425" in path else 404)
        return httpx.Response(200, content=b"y2_statefips,y2_countyfips\n")

    assert irs.discover(client_for(handler)) == ["2324"]
    keys = irs.fetch("2026-09-19", store=local_store, client=client_for(handler))
    assert keys[-2:] == [
        "raw/irs/2026-09-19/countyinflow2324.csv",
        "raw/irs/2026-09-19/countyoutflow2324.csv",
    ]


def test_irs_fetches_both_flows_for_every_year_pair(local_store: LocalStore, monkeypatch):
    monkeypatch.setattr("pipeline.ingest.irs.source", lambda _id: IRS_ENTRY)
    urls = []

    def handler(request):
        if request.method == "HEAD":
            return httpx.Response(404)
        urls.append(str(request.url))
        return httpx.Response(200, content=b"y2_statefips,y2_countyfips\n")

    keys = irs.fetch("2026-09-19", store=local_store, client=client_for(handler))
    assert keys == [
        "raw/irs/2026-09-19/countyinflow2122.csv",
        "raw/irs/2026-09-19/countyoutflow2122.csv",
        "raw/irs/2026-09-19/countyinflow2223.csv",
        "raw/irs/2026-09-19/countyoutflow2223.csv",
    ]
    assert urls[0] == "https://www.irs.gov/pub/irs-soi/countyinflow2122.csv"
    assert read_meta(local_store, keys[-1])["url"].endswith("countyoutflow2223.csv")
    # a rerun is a no-op
    assert irs.fetch("2026-09-19", store=local_store, client=client_for(handler)) == keys
    assert len(urls) == 4
