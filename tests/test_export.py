"""Export shaping: latest runs, the methodology block and the dataset CSV, without D1."""

from __future__ import annotations

import csv
import json

from pipeline.export import latest_momentum, latest_scores, methodology, write_dataset_csv


def run_row(geoid, computed_at, total, label, **extra):
    return {
        "geoid": geoid,
        "config_version": "v1",
        "computed_at": computed_at,
        "coverage": 1.0,
        "factor_scores": json.dumps({"x": 0.5}),
        "factor_inputs": json.dumps({}),
        **{k: v for k, v in extra.items()},
        **({"momentum": total, "label": label} if "momentum" in extra else {}),
    }


def test_latest_runs_pick_the_newest_computed_at():
    scores = [
        {**run_row("1", "2026-09-01T00:00:00", 0, None), "readiness": 50.0, "grade": "C"},
        {**run_row("1", "2026-09-02T00:00:00", 0, None), "readiness": 60.0, "grade": "B"},
    ]
    assert latest_scores(scores, "v1")["1"]["readiness"] == 60.0
    momentum = [
        {**run_row("1", "2026-09-01T00:00:00", 0, None), "momentum": 45.0, "label": "steady"},
        {**run_row("1", "2026-09-03T00:00:00", 0, None), "momentum": 70.0, "label": "rising"},
    ]
    latest = latest_momentum(momentum, "v1")["1"]
    assert latest["momentum"] == 70.0 and latest["label"] == "rising"
    assert "readiness" not in latest and latest_momentum(momentum, "v9") == {}


def test_methodology_carries_both_configs():
    m = methodology("v1")
    assert [f["name"] for f in m["factors"]][:2] == ["access", "building_stock"]
    mo = m["momentum"]
    assert mo["version"] == "v2" and mo["min_coverage"] == 0.75
    assert mo["kind"] == "momentum" and mo["grading"]["method"] == "threshold"
    assert mo["grading"]["bands"] == {"rising": 60, "steady": 40, "fading": 0}
    inputs = {i["name"]: i for f in mo["factors"] for i in f["inputs"]}
    assert inputs["zhvi_change_1y_ny_median"]["context_only"] is True
    assert inputs["zhvi_change_1y_ny_median"]["curve"] is None
    assert "percentage points" in inputs["zhvi_change_1y"]["curve"]
    assert inputs["county_net_migration_rate_ny_median"]["context_only"] is True
    assert "per 1,000 filers" in inputs["county_net_migration_rate"]["curve"]
    assert [f["name"] for f in methodology("v1", "v1")["momentum"]["factors"]] == [
        "prices",
        "building",
        "people",
    ]
    assert "zhvi_change_1y" in m["metrics"] and m["metrics"]["permit_rate_change"]["format"]


def test_dataset_csv_has_momentum_columns(tmp_path):
    towns = [
        {
            "geoid": "1",
            "slug": "a-ny",
            "name": "A",
            "legal_type": "village",
            "county": "Greene",
            "region": "Capital Region",
            "pop_latest": 1000,
        }
    ]
    metrics = {"1": {"zhvi_change_1y": {"value": 0.05, "period": "2026-08", "suppressed": False}}}
    scores = {"1": {"readiness": 55.0, "grade": "B", "coverage": 0.9}}
    momentum = {"1": {"momentum": 62.5, "label": "rising", "coverage": 1.0}}
    path = tmp_path / "d.csv"
    assert write_dataset_csv(towns, metrics, scores, path, momentum) == 1
    (row,) = list(csv.DictReader(path.open()))
    assert row["momentum"] == "62.5" and row["momentum_label"] == "rising"
    assert row["zhvi_change_1y"] == "0.05" and row["zhvi_change_1y_period"] == "2026-08"
