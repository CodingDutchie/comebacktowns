"""Scoring engine: curves, factor maths, coverage, grading bands, explain, pilot rule."""

from __future__ import annotations

import pytest

from pipeline.qa import QAError
from pipeline.qa.pilot import PilotFixtureMissingError, check_pilot, load_pilot
from pipeline.scope import Town
from pipeline.score.curves import CURVES_V1, Linear, Peak, Recency
from pipeline.score.engine import assign_grades, explain, latest_rows, score_all
from pipeline.settings import scoring_config


def town(geoid: str, name: str, pop: int) -> Town:
    return Town(
        geoid=geoid,
        name=name,
        legal_type="village",
        county="Greene",
        county_fips="039",
        region="Capital Region",
        lat=42.2,
        lon=-73.9,
        pop_latest=pop,
        pop_latest_year=2024,
        slug=f"{name.lower()}-ny",
    )


def row(geoid, metric, value, period="2020-2024", suppressed=0):
    return {
        "geoid": geoid,
        "metric": metric,
        "period": period,
        "value": value,
        "moe": None,
        "suppressed": suppressed,
        "source_id": "test",
        "as_of": "2026-09-18",
        "r2_key": f"raw/test/{metric}",
    }


FULL = {
    "drive_min_nyc": 120,  # halfway between 60 and 240 -> 0.667
    "drive_min_regional_hub": 15,  # 1
    "miles_to_rail_station": 2,  # 1
    "pre1940_share": 0.35,  # 0.5
    "has_nrhp_district": 1,
    "osm_business_per_1k": 11,  # 0.5
    "median_home_value": 240_000,
    "metro_median_home_value": 400_000,  # ratio 0.6 -> peak 1
    "broadband_subscription_share": 0.7,  # 0.5
    "under_18_share": 0.185,  # 0.5
    "hospital_within_20min": 1,
    "dri_award_amount": 10_000_000,  # 1
    "dri_award_year": 2024,  # within 3 years -> 1
}


def test_curves_are_explicit():
    assert Linear("x", zero_at=240, one_at=60)(120) == pytest.approx(2 / 3)
    assert Linear("x", zero_at=240, one_at=60)(30) == 1.0 and Linear("x", 240, 60)(500) == 0.0
    peak = Peak("p", 0.25, 0.6, 1.2, "w")
    assert (
        peak(0.6) == 1.0
        and peak(0.25) == 0.0
        and peak(1.2) == 0.0
        and peak(0.9) == pytest.approx(0.5)
    )
    rec = Recency("r", 3, 10, 0.3)
    assert rec(2024, scoring_year=2026) == 1.0 and rec(2016, scoring_year=2026) == 0.3
    assert rec(2019, scoring_year=2026) == pytest.approx(1 - 0.7 * 4 / 7)
    for name in CURVES_V1:
        assert CURVES_V1[name].describe().startswith(name) or "ratio" in CURVES_V1[name].describe()


def test_every_scoring_input_has_a_curve_or_is_context():
    from pipeline.score.curves import CONTEXT_ONLY

    for factor in scoring_config("v1")["factors"].values():
        for name in factor["inputs"]:
            assert name in CURVES_V1 or name in CONTEXT_ONLY, name


def test_latest_rows_keeps_newest_period():
    rows = [
        row("1", "zhvi", 1, "2026-07"),
        row("1", "zhvi", 2, "2026-08"),
        row("1", "zhvi", 0, "2025-12"),
    ]
    assert latest_rows(rows)["1"]["zhvi"]["value"] == 2


def test_full_town_score_and_contributions():
    t = town("3600001", "Full", 3000)
    rows = [row(t.geoid, m, v) for m, v in FULL.items()]
    (score,) = score_all([t], rows, scoring_year=2026, computed_at="2026-09-18T00:00:00+00:00")
    assert score.coverage == 1.0
    fs = score.factor_scores
    assert fs["access"] == pytest.approx((2 / 3 + 1 + 1) / 3, abs=1e-4)
    assert fs["building_stock"] == pytest.approx(0.75)
    assert fs["main_street"] == pytest.approx(0.5)
    assert fs["price_headroom"] == pytest.approx(1.0)
    assert fs["services"] == pytest.approx((0.5 + 0.5 + 1) / 3, abs=1e-4)
    assert fs["civic_capacity"] == pytest.approx(1.0)
    expected = 100 * (0.25 * fs["access"] + 0.15 * (0.75 + 0.5 + 1.0 + fs["services"] + 1.0))
    assert score.readiness == pytest.approx(expected, abs=0.05)
    # contributions add up to the total
    total = sum(i.contribution or 0 for i in score.inputs.values())
    assert total == pytest.approx(score.readiness, abs=0.1)
    assert score.inputs["median_home_value"].contribution == pytest.approx(15.0, abs=0.01)
    assert score.inputs["metro_median_home_value"].contribution is None


def test_missing_and_suppressed_inputs_are_excluded_not_zero():
    t = town("3600002", "Sparse", 3000)
    rows = [
        row(t.geoid, m, v)
        for m, v in FULL.items()
        if m not in ("osm_business_per_1k", "dri_award_year", "pre1940_share")
    ]
    rows.append(row(t.geoid, "pre1940_share", 0.35, suppressed=1))
    (score,) = score_all([t], rows, scoring_year=2026)
    assert score.factor_scores["main_street"] is None
    assert score.inputs["osm_business_per_1k"].status == "missing"
    assert score.inputs["pre1940_share"].status == "suppressed"
    assert score.factor_scores["building_stock"] == 1.0  # only the district flag remains
    # 11 counted inputs (dri_award_year is conditional and absent), 9 usable
    assert score.coverage == pytest.approx(9 / 11)
    # weights renormalise over factors with any usable input
    assert score.readiness > 0


def test_no_award_town_is_complete_not_missing():
    t = town("3600003", "Quiet", 3000)
    rows = [row(t.geoid, m, v) for m, v in FULL.items() if not m.startswith("dri_")]
    rows.append(row(t.geoid, "dri_award_amount", 0))
    (score,) = score_all([t], rows, scoring_year=2026)
    assert score.inputs["dri_award_year"].status == "not_applicable"
    assert score.factor_scores["civic_capacity"] == 0.0 and score.coverage == 1.0


def test_price_headroom_needs_its_context():
    t = town("3600004", "NoMetro", 3000)
    rows = [row(t.geoid, m, v) for m, v in FULL.items() if m != "metro_median_home_value"]
    (score,) = score_all([t], rows, scoring_year=2026)
    assert score.inputs["median_home_value"].status == "missing"
    assert score.factor_scores["price_headroom"] is None


def test_grades_curve_within_population_bands():
    towns = [town(f"36000{i:02d}", f"T{i}", 1000 if i < 10 else 20000) for i in range(20)]
    rows = []
    for i, t in enumerate(towns):
        for m, v in FULL.items():
            if m != "drive_min_nyc":
                rows.append(row(t.geoid, m, v))
        rows.append(row(t.geoid, "drive_min_nyc", 60 + 9 * i))  # spread readiness
    scores = score_all(towns, rows, scoring_year=2026)
    small = [s for s in scores if s.band == "under_5000"]
    big = [s for s in scores if s.band == "5000_plus"]
    assert len(small) == len(big) == 10
    for group in (small, big):
        letters = [s.grade for s in group]
        # percentiles 5,15,...,95 against bands A>=90, B>=75, C>=50, D>=25
        assert {g: letters.count(g) for g in "ABCDF"} == {"A": 1, "B": 2, "C": 2, "D": 3, "F": 2}
        best = max(group, key=lambda s: s.readiness)
        assert best.grade == "A"
    # coverage below the floor removes the grade
    scores[0].coverage = 0.5
    assign_grades(scores, {t.geoid: t for t in towns}, scoring_config("v1"))
    assert scores[0].grade is None and any("no grade" in n for n in scores[0].notes)


def test_explain_is_an_audit_trail():
    t = town("3613002", "Catskill", 3723)
    rows = [row(t.geoid, m, v) for m, v in FULL.items()]
    (score,) = score_all([t], rows, scoring_year=2026, computed_at="2026-09-18T00:00:00+00:00")
    from pipeline.score.curves import CURVES

    text = explain(score, t, scoring_config("v1"), CURVES["v1"])
    assert "Catskill (village, Greene County" in text
    for name in FULL:
        assert name in text
    assert "raw/test/median_home_value" in text and "curve:" in text and "contributes" in text


def test_pilot_rule(tmp_path):
    t = town("3613002", "Catskill", 3723)
    rows = [row(t.geoid, m, v) for m, v in FULL.items()]
    (score,) = score_all([t], rows, scoring_year=2026)
    with pytest.raises(PilotFixtureMissingError):
        load_pilot(tmp_path / "missing.csv")
    fixture = tmp_path / "pilot_v0.csv"
    fixture.write_text(f"slug,name,readiness\ncatskill-ny,Catskill,{score.readiness + 2:.1f}\n")
    lines = check_pilot([score], {t.geoid: t.slug}, load_pilot(fixture))
    assert lines and "drift" in lines[0]
    fixture.write_text(f"geoid,readiness\n3613002,{score.readiness + 4:.1f}\n")
    with pytest.raises(QAError, match="exceeds"):
        check_pilot([score], {t.geoid: t.slug}, load_pilot(fixture))
