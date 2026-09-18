"""Transforms against small synthetic snapshots in a local store."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from pipeline.qa import QAError
from pipeline.qa.metrics import check_coverage, coverage_report, validate_metrics
from pipeline.scope import build_towns
from pipeline.transform import Context, MetricRow, suppress_if_wide
from pipeline.transform.acs import acs_metrics, load_group, ratio
from pipeline.transform.dri import community_names, dri_metrics
from pipeline.transform.nrhp import nrhp_metrics
from pipeline.transform.osm import osm_metrics
from pipeline.transform.osrm import crow_metrics, osrm_metrics
from pipeline.transform.permits import parse_place_file, permits_metrics
from pipeline.transform.popest import popest_metrics
from pipeline.transform.rail import rail_metrics
from pipeline.transform.zillow import latest_values, zillow_metrics

AS = "2026-09-18"


def acs_doc(table: str, geo: str, rows: dict[str, dict[str, str]]) -> bytes:
    """rows: geoid -> {var: value}; geo columns derived from the geoid."""
    variables = sorted({v for r in rows.values() for v in r})
    if geo == "place":
        header = ["NAME", *variables, "state", "place"]
        body = [["x", *[r.get(v) for v in variables], g[:2], g[2:]] for g, r in rows.items()]
    elif geo == "county":
        header = ["NAME", *variables, "state", "county"]
        body = [["x", *[r.get(v) for v in variables], g[:2], g[2:]] for g, r in rows.items()]
    elif geo == "cbsa":
        header = ["NAME", *variables, "metropolitan statistical area/micropolitan statistical area"]
        body = [["x", *[r.get(v) for v in variables], g] for g, r in rows.items()]
    else:
        raise ValueError(geo)
    return json.dumps([header, *body]).encode()


@pytest.fixture
def ctx(local_store, popest_bytes, gazetteer_zip, scope):
    towns = build_towns(popest_bytes, gazetteer_zip, scope)
    local_store.put_bytes(f"raw/popest/{AS}/sub-est2024.csv", popest_bytes)
    local_store.put_bytes(f"raw/gazetteer/{AS}/2024_Gaz_place_national.zip", gazetteer_zip)
    return Context(store=local_store, as_of=AS, towns=towns)


def test_suppression_rule():
    assert suppress_if_wide(100, 41) == 1 and suppress_if_wide(100, 40) == 0
    assert suppress_if_wide(0, 5) == 1 and suppress_if_wide(None, 5) == 0


def test_ratio_moe_uses_census_formula():
    vars_ = {"AE": 20.0, "AM": 4.0, "BE": 100.0, "BM": 10.0}
    p, moe = ratio(vars_, ["A"], "B")
    assert p == 0.2
    assert abs(moe - ((4**2 - 0.2**2 * 10**2) ** 0.5) / 100) < 1e-9


def test_load_group_sentinels_and_geoid():
    doc = acs_doc("B25077", "place", {"3613002": {"B25077_001E": "-666666666", "B25077_001M": "5"}})
    data = load_group(doc, "place")
    assert data["3613002"]["B25077_001E"] is None and data["3613002"]["B25077_001M"] == 5.0


def test_acs_metrics_end_to_end(ctx):
    s = ctx.store
    place = {
        "3613002": {"B25077_001E": "250000", "B25077_001M": "20000"},
        "3639727": {"B25077_001E": "300000", "B25077_001M": "150000"},  # MOE 50% -> suppressed
    }
    s.put_bytes(f"raw/acs/{AS}/acs5_2024_B25077_place.json", acs_doc("B25077", "place", place))
    for table, vars_ in {
        "B25064": {"B25064_001E": "1200", "B25064_001M": "100"},
        "B19013": {"B19013_001E": "60000", "B19013_001M": "5000"},
        "B25002": {
            "B25002_001E": "1000",
            "B25002_001M": "50",
            "B25002_003E": "100",
            "B25002_003M": "30",
        },
        "B25034": {
            "B25034_001E": "1000",
            "B25034_001M": "50",
            "B25034_011E": "500",
            "B25034_011M": "60",
        },
        "B28002": {
            "B28002_001E": "900",
            "B28002_001M": "40",
            "B28002_007E": "700",
            "B28002_007M": "50",
        },
        "B17001": {
            "B17001_001E": "3000",
            "B17001_001M": "100",
            "B17001_002E": "450",
            "B17001_002M": "100",
        },
        "B08303": {
            "B08303_001E": "1500",
            "B08303_001M": "80",
            "B08303_012E": "100",
            "B08303_012M": "40",
            "B08303_013E": "50",
            "B08303_013M": "30",
        },
        "B14001": {
            "B14001_003E": "50",
            "B14001_003M": "20",
            "B14001_004E": "50",
            "B14001_004M": "20",
            "B14001_005E": "200",
            "B14001_005M": "40",
            "B14001_006E": "200",
            "B14001_006M": "40",
            "B14001_007E": "200",
            "B14001_007M": "40",
        },
        "B09001": {"B09001_001E": "800", "B09001_001M": "60"},
        "B01003": {"B01003_001E": "4000", "B01003_001M": "100"},
    }.items():
        rows = {g: vars_ for g in place}
        s.put_bytes(f"raw/acs/{AS}/acs5_2024_{table}_place.json", acs_doc(table, "place", rows))
    prior14 = {
        g: {
            "B14001_003E": "60",
            "B14001_003M": "20",
            "B14001_004E": "60",
            "B14001_004M": "20",
            "B14001_005E": "260",
            "B14001_005M": "40",
            "B14001_006E": "260",
            "B14001_006M": "40",
            "B14001_007E": "260",
            "B14001_007M": "40",
        }
        for g in place
    }
    s.put_bytes(f"raw/acs/{AS}/acs5_2019_B14001_place.json", acs_doc("B14001", "place", prior14))
    prior09 = {g: {"B09001_001E": "1000", "B09001_001M": "60"} for g in place}
    s.put_bytes(f"raw/acs/{AS}/acs5_2019_B09001_place.json", acs_doc("B09001", "place", prior09))
    s.put_bytes(
        f"raw/acs/{AS}/acs5_2024_B25077_county.json",
        acs_doc(
            "B25077",
            "county",
            {
                "36039": {"B25077_001E": "280000", "B25077_001M": "9000"},
                "36111": {"B25077_001E": "320000", "B25077_001M": "9000"},
                "36021": {"B25077_001E": "1", "B25077_001M": "0"},
            },
        ),
    )
    s.put_bytes(
        f"raw/acs/{AS}/acs5_2024_B25077_cbsa.json",
        acs_doc("B25077", "cbsa", {"28740": {"B25077_001E": "330000", "B25077_001M": "8000"}}),
    )
    # permits file supplies the CBSA crosswalk: Kingston -> 28740, Catskill -> none
    header = "Survey,State,6-Digit,County,Census Place,FIPS Place,FIPS MCD,Pop,CSA,CBSA,Footnote,Central,Zip,Region,Division,Number of,Place,,1-unit,,,2-units,,,3-4 units,,,5+ units,,,1-unit rep,,,2-units rep,,,3-4 units rep,,,5+ units rep\nDate,Code,...\n \n"
    body = "2025,36,119000,039,0560,13002 ,13013 ,3815 ,999,99999, , ,12414,1,2,12,Catskill village,2,2,500000,0,0,0,0,0,0,0,0,0,2,2,500000,0,0,0,0,0,0,0,0,0\n2025,36,1,111,0,39727 ,0 ,24000 ,1,28740, , ,12401,1,2,12,Kingston city,10,10,2,1,2,3,0,0,0,1,4,5,0,0,0,0,0,0,0,0,0,0,0,0\n"
    s.put_bytes(f"raw/permits/{AS}/ne2025a.txt", (header + body).encode())

    rows = acs_metrics(ctx)
    by = {(r.geoid, r.metric): r for r in rows}
    assert (
        by[("3613002", "median_home_value")].value == 250000
        and by[("3613002", "median_home_value")].suppressed == 0
    )
    assert by[("3639727", "median_home_value")].suppressed == 1
    assert abs(by[("3613002", "vacancy_rate")].value - 0.1) < 1e-9
    assert abs(by[("3613002", "pre1940_share")].value - 0.5) < 1e-9
    assert abs(by[("3613002", "commute_60plus_share")].value - 0.1) < 1e-9
    assert by[("3613002", "k12_enrollment")].value == 700
    assert abs(by[("3613002", "school_enrollment_trend")].value - (700 - 900) / 900) < 1e-9
    assert by[("3613002", "school_enrollment_trend")].period == "2015-2019 to 2020-2024"
    share = by[("3613002", "under_18_share")]
    assert abs(share.value - 0.2) < 1e-9 and share.suppressed == 0
    assert abs(share.moe - ((60**2 - 0.2**2 * 100**2) ** 0.5) / 4000) < 1e-9
    assert by[("3613002", "county_median_home_value")].value == 280000
    assert by[("3613002", "metro_median_home_value")].value == 280000  # no CBSA -> county
    assert by[("3613002", "metro_median_home_value")].r2_key.endswith("_county.json")
    assert by[("3639727", "metro_median_home_value")].value == 330000  # Kingston is in a CBSA
    assert by[("3639727", "cbsa_median_home_value")].value == 330000
    assert all(r.r2_key.startswith("raw/acs/") and r.as_of == AS for r in rows)


def test_popest_metrics(ctx):
    rows = {(r.geoid, r.metric): r for r in popest_metrics(ctx)}
    assert (
        rows[("3613002", "population")].value == 3900
        and rows[("3613002", "population")].period == "2024"
    )
    assert abs(rows[("3613002", "population_change")].value - 100 / 3800) < 1e-9


PERMIT_HEADER = "h1\nh2\n \n"


def permit_line(year, place, months, units1, units5=0):
    cols = ["0"] * 42
    cols[0], cols[1], cols[5], cols[9], cols[15], cols[16] = (
        str(year),
        "36",
        place,
        "99999",
        str(months),
        "x",
    )
    cols[18], cols[27] = str(units1), str(units5)
    return ",".join(cols) + "\n"


def test_permits_rolling_mean_and_suppression(ctx):
    s = ctx.store
    for year, (m, u) in {
        2021: (12, 4),
        2022: (12, 4),
        2023: (12, 3),
        2024: (12, 6),
        2025: (12, 9),
    }.items():
        s.put_bytes(
            f"raw/permits/{AS}/ne{year}a.txt",
            (
                PERMIT_HEADER
                + permit_line(year, "13002", m, u)
                + permit_line(year, "39727", 12 if year != 2024 else 7, 30, 20)
            ).encode(),
        )
    rows = {(r.geoid, r.metric, r.period): r for r in permits_metrics(ctx)}
    catskill = rows[("3613002", "permits_per_1k", "2023-2025")]
    assert abs(catskill.value - ((3 + 6 + 9) / 3) / 3.9) < 1e-9 and catskill.suppressed == 0
    assert catskill.r2_key.endswith("ne2025a.txt")
    kingston = rows[("3639727", "permits_per_1k", "2023-2025")]
    assert kingston.suppressed == 1  # 2024 reported 7 months
    assert rows[("3639727", "permit_units", "2024")].value == 50
    assert parse_place_file((PERMIT_HEADER + permit_line(2025, "13002", 12, 1)).encode())[
        "13002"
    ] == (1, 12, "99999")


def test_zillow_latest_month_and_gaps(ctx):
    csv = (
        b"RegionID,SizeRank,RegionName,RegionType,StateName,State,Metro,CountyName,2026-06-30,2026-07-31,2026-08-31\n"
        b"1,1,Catskill,city,NY,NY,,Greene County,250000,255000,\n"
        b"2,2,Kingston,city,PA,PA,,Luzerne County,1,1,1\n"
    )
    ctx.store.put_bytes(f"raw/zillow/{AS}/zhvi_city.csv", csv)
    ctx.store.put_bytes(f"raw/zillow/{AS}/zori_city.csv", csv.replace(b"250000,255000,", b"1200,,"))
    assert latest_values(csv)[("Catskill", "Greene County")] == ("2026-07", 255000.0)
    rows = zillow_metrics(ctx)
    assert [(r.geoid, r.metric, r.period, r.value) for r in rows] == [
        ("3613002", "zhvi", "2026-07", 255000.0),
        ("3613002", "zori", "2026-06", 1200.0),
    ]


SQUARE_PLACES = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"GEOID": g},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [lon, lat],
                        [lon + 0.02, lat],
                        [lon + 0.02, lat + 0.02],
                        [lon, lat + 0.02],
                        [lon, lat],
                    ]
                ],
            },
        }
        for g, lat, lon in [
            ("3613002", 42.20, -73.87),
            ("3639727", 41.92, -74.01),
            ("3699004", 42.09, -74.11),
            ("3699005", 42.19, -74.21),
        ]
    ],
}


def test_nrhp_intersection(ctx):
    ctx.store.put_bytes(f"raw/tiger/{AS}/places_36.geojson", json.dumps(SQUARE_PLACES).encode())
    districts = {
        "features": [
            {
                "attributes": {"RESNAME": "East Side"},
                "geometry": {
                    "rings": [
                        [
                            [-73.865, 42.205],
                            [-73.86, 42.205],
                            [-73.86, 42.21],
                            [-73.865, 42.21],
                            [-73.865, 42.205],
                        ]
                    ]
                },
            }
        ]
    }
    ctx.store.put_bytes(f"raw/nrhp/{AS}/ny_districts_polygons.json", json.dumps(districts).encode())
    rows = {(r.geoid, r.metric): r.value for r in nrhp_metrics(ctx)}
    assert (
        rows[("3613002", "has_nrhp_district")] == 1
        and rows[("3613002", "nrhp_district_count")] == 1
    )
    assert rows[("3639727", "has_nrhp_district")] == 0


def test_rail_nearest_station_cites_its_file(ctx):
    s = ctx.store
    s.put_bytes(
        f"raw/rail/{AS}/amtrak_stations.json",
        json.dumps(
            {
                "features": [
                    {"attributes": {"StationName": "Hudson, NY", "lat": 42.2525, "lon": -73.7911}}
                ]
            }
        ).encode(),
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "stops.txt",
            "stop_id,stop_name,stop_lat,stop_lon,parent_station\n1,Poughkeepsie,41.7058,-73.9379,\n2,Highbridge Yard,40.83,-73.93,\n",
        )
    s.put_bytes(f"raw/rail/{AS}/gtfsmnr.zip", buf.getvalue())
    s.put_bytes(
        f"raw/rail/{AS}/manual_stations.yml",
        b"stations:\n  - {name: Port Jervis, lat: 41.3748, lon: -74.6926}\n",
    )
    rows = {r.geoid: r for r in rail_metrics(ctx)}
    assert rows["3613002"].r2_key.endswith("amtrak_stations.json") and rows["3613002"].value < 6
    assert rows["3639727"].r2_key.endswith("gtfsmnr.zip")


def test_osm_and_osrm_and_crow(ctx):
    s = ctx.store
    s.put_bytes(
        f"raw/osm/{AS}/3613002.json",
        json.dumps(
            {"elements": [{"tags": {"shop": "a"}}, {"tags": {"amenity": "cafe"}}, {"id": 3}]}
        ).encode(),
    )
    s.put_bytes(
        f"raw/osrm/{AS}/3613002.json",
        json.dumps(
            {
                "destinations": [
                    {"kind": "nyc", "duration_s": 9000},
                    {"kind": "hub", "duration_s": 2700},
                    {"kind": "hub", "duration_s": 2400},
                    {"kind": "hospital", "duration_s": 840},
                    {"kind": "hospital", "duration_s": None},
                ]
            }
        ).encode(),
    )
    osm = {r.metric: r.value for r in osm_metrics(ctx)}
    assert osm["osm_business_count"] == 2 and abs(osm["osm_business_per_1k"] - 2 / 3.9) < 1e-9
    osrm = {r.metric: r.value for r in osrm_metrics(ctx)}
    assert osrm == {
        "drive_min_nyc": 150.0,
        "drive_min_regional_hub": 40.0,
        "drive_min_nearest_hospital": 14.0,
        "hospital_within_20min": 1.0,
    }
    crow = {(r.geoid, r.metric): r for r in crow_metrics(ctx)}
    assert (
        95 < crow[("3613002", "crow_miles_nyc")].value < 110
        and crow[("3613002", "crow_miles_nyc")].source_id == "gazetteer"
    )


def test_community_names():
    assert community_names("Village of Clinton and Town of Kirkland") == ["Clinton", "Kirkland"]
    assert community_names("Tannersville’s Painted Village DRI District") == ["Tannersville"]
    assert community_names("Aurora, Cayuga, and Union Springs") == [
        "Aurora",
        "Cayuga",
        "Union Springs",
    ]
    assert community_names("The Village of Sleepy Hollow") == ["Sleepy Hollow"]
    assert community_names("Catskill") == ["Catskill"]


def test_dri_metrics_match_region_and_latest_award(ctx):
    s = ctx.store
    r2 = "<h2>Capital Region</h2><p><strong>Catskill</strong></p><p>text</p>"
    r8 = "<h2>Capital Region</h2><p><strong>Village of Catskill</strong></p><p>text</p><h2>Mid-Hudson</h2><p><strong>Kingston</strong></p>"
    n1 = "<h2>Mid-Hudson</h2><p><strong>Catskill</strong></p>"  # wrong region: must not match
    s.put_bytes(f"raw/dri/{AS}/dri_downtown-revitalization-initiative-round-two.html", r2.encode())
    s.put_bytes(
        f"raw/dri/{AS}/dri_downtown-revitalization-initiative-round-eight.html", r8.encode()
    )
    s.put_bytes(f"raw/dri/{AS}/nyf_ny-forward-round-one.html", n1.encode())
    manifest = {
        "dri": [
            {
                "kind": "round",
                "key": f"raw/dri/{AS}/dri_downtown-revitalization-initiative-round-two.html",
            },
            {
                "kind": "round",
                "key": f"raw/dri/{AS}/dri_downtown-revitalization-initiative-round-eight.html",
            },
        ],
        "nyf": [{"kind": "round", "key": f"raw/dri/{AS}/nyf_ny-forward-round-one.html"}],
    }
    s.put_bytes(f"raw/dri/{AS}/manifest.json", json.dumps(manifest).encode())
    rows = {(r.geoid, r.metric): r for r in dri_metrics(ctx)}
    assert rows[("3613002", "dri_award_count")].value == 2
    assert (
        rows[("3613002", "dri_award_year")].value == 2024
        and rows[("3613002", "dri_award_amount")].value == 10_000_000
    )
    assert rows[("3613002", "dri_award_year")].r2_key.endswith("round-eight.html")
    assert (
        rows[("3639727", "dri_award_count")].value == 1
        and rows[("3639727", "dri_award_year")].value == 2024
    )
    assert (
        rows[("3699004", "dri_award_amount")].value == 0
        and ("3699004", "dri_award_year") not in rows
    )


def test_validate_metrics_rules(ctx):
    good = MetricRow(
        geoid="3613002",
        metric="vacancy_rate",
        period="2020-2024",
        value=0.1,
        moe=0.02,
        source_id="acs",
        as_of=AS,
        r2_key="raw/acs/x.json",
    )
    validate_metrics([good])
    bad_bounds = good.model_copy(update={"value": 0.9})
    bad_flag = good.model_copy(update={"moe": 0.09, "suppressed": 0})
    unknown = good.model_copy(update={"metric": "made_up"})
    with pytest.raises(QAError) as exc:
        validate_metrics([bad_bounds, bad_flag, unknown, good, good])
    text = str(exc.value)
    assert (
        "outside [0, 0.6]" in text
        and "suppression flag" in text
        and "no sanity bounds" in text
        and "duplicate" in text
    )


def test_coverage_gate(ctx):
    rows = [
        MetricRow(
            geoid=t.geoid,
            metric="drive_min_nyc",
            period="2026-09",
            value=100,
            source_id="osrm",
            as_of=AS,
            r2_key="raw/osrm/x",
        )
        for t in ctx.towns
    ]
    rows.append(
        MetricRow(
            geoid=ctx.towns[0].geoid,
            metric="broadband_subscription_share",
            period="p",
            value=0.8,
            source_id="acs",
            as_of=AS,
            r2_key="raw/acs/x",
        )
    )
    report = coverage_report(rows, len(ctx.towns))
    assert (
        report["drive_min_nyc"] == 1.0
        and report["broadband_100_share"] == 0.25
        and report["dri_award_year"] == 0.0
    )
    with pytest.raises(QAError) as exc:
        check_coverage(report)
    assert "dri_award_year" not in str(exc.value) and "broadband_100_share" in str(exc.value)


def test_latest_snapshot_resolves_on_or_before_as_of(
    local_store, popest_bytes, gazetteer_zip, scope
):
    from pipeline.transform import latest_snapshot, snapshot_dates

    for date in ("2026-08-01", "2026-09-01", "2026-10-01"):
        local_store.put_bytes(f"raw/zillow/{date}/zhvi_city.csv", b"RegionID\n")
    assert snapshot_dates(local_store, "zillow") == ["2026-08-01", "2026-09-01", "2026-10-01"]
    assert latest_snapshot(local_store, "zillow", "2026-09-15") == "2026-09-01"
    assert latest_snapshot(local_store, "zillow", "2026-10-01") == "2026-10-01"
    with pytest.raises(FileNotFoundError, match="no raw snapshot of zillow"):
        latest_snapshot(local_store, "zillow", "2026-07-31")
    with pytest.raises(FileNotFoundError, match="acs"):
        latest_snapshot(local_store, "acs", "2026-09-15")


def test_rows_carry_their_sources_snapshot_date(local_store, popest_bytes, gazetteer_zip, scope):
    """A monthly run on 2026-10-05 reuses the September popest and stamps rows with it."""
    towns = build_towns(popest_bytes, gazetteer_zip, scope)
    local_store.put_bytes("raw/popest/2026-09-18/sub-est2024.csv", popest_bytes)
    ctx = Context(store=local_store, as_of="2026-10-05", towns=towns)
    rows = popest_metrics(ctx)
    assert rows and all(r.as_of == "2026-09-18" for r in rows)
    assert all(r.r2_key.startswith("raw/popest/2026-09-18/") for r in rows)
