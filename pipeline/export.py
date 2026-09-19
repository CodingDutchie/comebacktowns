"""Export D1 into the JSON the static site builds from, plus the downloadable dataset.

Output goes to ``site/data/`` (gitignored) and ``site/public/downloads/``. Nothing here is
raw data: it is the canonical tables, shaped for rendering.
"""

from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline.load.d1 import D1Client
from pipeline.score.curves import CONTEXT_ONLY, CURVES, MOMENTUM_CURVES, Curve
from pipeline.settings import (
    CONFIG_DIR,
    ROOT,
    load_yaml,
    momentum_config,
    scoring_config,
    site_config,
    sources_config,
)

log = logging.getLogger(__name__)

SITE_DATA = ROOT / "site" / "data"
DOWNLOADS = ROOT / "site" / "public" / "downloads"


def metrics_config() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "metrics.yml")


def latest_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        current = out[row["geoid"]].get(row["metric"])
        if current is None or str(row["period"]) > str(current["period"]):
            out[row["geoid"]][row["metric"]] = {
                "period": row["period"],
                "value": row["value"],
                "moe": row["moe"],
                "suppressed": bool(row["suppressed"]),
                "source_id": row["source_id"],
                "as_of": row["as_of"],
                "r2_key": row["r2_key"],
            }
    return dict(out)


def latest_run(
    rows: list[dict[str, Any]], version: str, *, total: str = "readiness", label: str = "grade"
) -> dict[str, dict[str, Any]]:
    """The newest computed_at run for the config version, one entry per town. ``total`` and
    ``label`` name the table's score and grade columns (momentum, label for momentum)."""
    runs = [r for r in rows if r["config_version"] == version]
    if not runs:
        return {}
    newest = max(r["computed_at"] for r in runs)
    out: dict[str, dict[str, Any]] = {}
    for row in runs:
        if row["computed_at"] != newest:
            continue
        out[row["geoid"]] = {
            total: row[total],
            label: row[label],
            "coverage": row["coverage"],
            "computed_at": row["computed_at"],
            "config_version": row["config_version"],
            "factor_scores": json.loads(row["factor_scores"]),
            "inputs": json.loads(row["factor_inputs"]),
        }
    return out


def latest_scores(rows: list[dict[str, Any]], version: str) -> dict[str, dict[str, Any]]:
    return latest_run(rows, version)


def latest_momentum(rows: list[dict[str, Any]], version: str) -> dict[str, dict[str, Any]]:
    return latest_run(rows, version, total="momentum", label="label")


def factor_block(
    config: dict[str, Any], curves: dict[str, Curve], qa: dict[str, Any]
) -> list[dict[str, Any]]:
    factors = []
    for name, spec in config["factors"].items():
        inputs = []
        for inp in spec["inputs"]:
            inputs.append(
                {
                    "name": inp,
                    "metric": qa["coverage"].get("input_aliases", {}).get(inp, inp),
                    "context_only": inp in CONTEXT_ONLY,
                    "curve": None if inp in CONTEXT_ONLY else curves[inp].describe(),
                    "conditional": inp in qa["coverage"].get("conditional_inputs", []),
                }
            )
        factors.append({"name": name, "weight": spec["weight"], "inputs": inputs})
    return factors


def methodology(version: str, momentum_version: str = "v1") -> dict[str, Any]:
    config = scoring_config(version)
    qa = load_yaml(CONFIG_DIR / "qa.yml")
    mconfig = momentum_config(momentum_version)
    return {
        "version": config["version"],
        "factors": factor_block(config, CURVES[version], qa),
        "grading": config["grading"],
        "min_coverage": config["min_coverage"],
        "momentum": {
            "version": mconfig["version"],
            "kind": mconfig.get("kind", "momentum"),
            "factors": factor_block(mconfig, MOMENTUM_CURVES[momentum_version], qa),
            "grading": mconfig["grading"],
            "min_coverage": mconfig["min_coverage"],
        },
        "suppression": {
            "moe_threshold": 0.4,
            "text": (
                "Any American Community Survey figure whose margin of error exceeds 40% of "
                "the estimate is kept but marked suppressed: it is shown as not available at "
                "this sample size and excluded from the score. Permit rates are suppressed "
                "when any of the three years was reported for fewer than twelve months."
            ),
        },
        "bounds": qa["bounds"],
        "metrics": metrics_config(),
    }


def sources_block(metric_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last_pull: dict[str, str] = {}
    for row in metric_rows:
        last_pull[row["source_id"]] = max(last_pull.get(row["source_id"], ""), row["as_of"])
    out = []
    for source_id, entry in sources_config().items():
        out.append(
            {
                "id": source_id,
                "name": entry.get("name"),
                "publisher": entry.get("publisher"),
                "licence": entry.get("licence"),
                "attribution": entry.get("attribution"),
                "cadence": entry.get("cadence"),
                "used_for": entry.get("used_for"),
                "url": entry.get("url")
                or entry.get("amtrak_url")
                or ", ".join(entry.get("pages", {}).values())
                or ", ".join(entry.get("files", {}).values()),
                "last_pull": last_pull.get(source_id),
            }
        )
    return out


def write_dataset_csv(
    towns: list[dict[str, Any]],
    metrics: dict[str, dict[str, dict[str, Any]]],
    scores: dict[str, dict[str, Any]],
    path: Path,
    momentum: dict[str, dict[str, Any]] | None = None,
) -> int:
    momentum = momentum or {}
    metric_names = sorted({m for per_town in metrics.values() for m in per_town})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        header = [
            "geoid",
            "slug",
            "name",
            "legal_type",
            "county",
            "region",
            "population",
            "readiness",
            "grade",
            "coverage",
            "momentum",
            "momentum_label",
            "momentum_coverage",
        ]
        for m in metric_names:
            header += [m, f"{m}_period", f"{m}_suppressed"]
        writer.writerow(header)
        for town in towns:
            score = scores.get(town["geoid"], {})
            mo = momentum.get(town["geoid"], {})
            row = [
                town["geoid"],
                town["slug"],
                town["name"],
                town["legal_type"],
                town["county"],
                town["region"],
                town["pop_latest"],
                score.get("readiness"),
                score.get("grade"),
                score.get("coverage"),
                mo.get("momentum"),
                mo.get("label"),
                mo.get("coverage"),
            ]
            per_town = metrics.get(town["geoid"], {})
            for m in metric_names:
                hit = per_town.get(m)
                row += [
                    hit["value"] if hit else None,
                    hit["period"] if hit else None,
                    int(hit["suppressed"]) if hit else None,
                ]
            writer.writerow(row)
    return len(towns)


def export_site_data(
    d1: D1Client,
    *,
    version: str = "v1",
    momentum_version: str = "v1",
    out_dir: Path = SITE_DATA,
) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    towns = d1.query("SELECT * FROM towns ORDER BY name, county")
    from pipeline.load.scores import read_metrics

    metric_rows = read_metrics(d1)
    score_rows = d1.query("SELECT * FROM scores")
    momentum_rows = d1.query("SELECT * FROM momentum")
    metrics = latest_metrics(metric_rows)
    scores = latest_scores(score_rows, version)
    momentum = latest_momentum(momentum_rows, momentum_version)
    generated = datetime.now(UTC).isoformat(timespec="seconds")
    payloads: dict[str, Any] = {
        "towns.json": towns,
        "metrics.json": metrics,
        "scores.json": scores,
        "momentum.json": momentum,
        "methodology.json": methodology(version, momentum_version),
        "sources.json": sources_block(metric_rows),
        "meta.json": {
            "generated_at": generated,
            "site": site_config(),
            "town_count": len(towns),
            "scored_count": len(scores),
            "momentum_count": len(momentum),
        },
    }
    for name, payload in payloads.items():
        (out_dir / name).write_text(json.dumps(payload, indent=None, separators=(",", ":")))
    rows = write_dataset_csv(
        towns, metrics, scores, DOWNLOADS / "comebacktowns-dataset.csv", momentum
    )
    log.info(
        "export: %d towns, %d scored, %d with momentum, %d metric rows, dataset %d rows",
        len(towns),
        len(scores),
        len(momentum),
        len(metric_rows),
        rows,
    )
    return {
        "towns": len(towns),
        "scored": len(scores),
        "momentum": len(momentum),
        "metric_rows": len(metric_rows),
    }
