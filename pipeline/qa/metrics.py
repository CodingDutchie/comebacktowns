"""QA rules 1, 3 and 5 over metric rows, plus the Phase 2 coverage gate."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from pipeline.qa import QAError
from pipeline.settings import CONFIG_DIR, load_yaml, scoring_config
from pipeline.transform import MetricRow, suppress_if_wide


def qa_config() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "qa.yml")


def validate_metrics(rows: list[MetricRow], config: dict[str, Any] | None = None) -> None:
    config = config or qa_config()
    bounds = config["bounds"]
    problems: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        ident = f"{row.geoid} {row.metric} {row.period}"
        # rule 3: provenance on every row (the model enforces the shape; check emptiness too)
        if not row.as_of or not row.r2_key:
            problems.append(f"{ident}: missing as_of or r2_key")
        # rule 1: ACS suppression must have been applied
        if row.source_id == "acs" and row.suppressed != suppress_if_wide(row.value, row.moe):
            problems.append(f"{ident}: suppression flag disagrees with the 40% MOE rule")
        # rule 5: sanity bounds
        if row.value is not None:
            if row.metric not in bounds:
                problems.append(f"{ident}: no sanity bounds configured for {row.metric}")
            else:
                lo, hi = bounds[row.metric]
                if not (lo <= row.value <= hi):
                    problems.append(f"{ident}: value {row.value} outside [{lo}, {hi}]")
        key = (row.geoid, row.metric, row.period)
        if key in seen:
            problems.append(f"{ident}: duplicate row")
        seen.add(key)
    if problems:
        raise QAError(
            problems[:50] + ([f"... {len(problems) - 50} more"] if len(problems) > 50 else [])
        )


def coverage_report(
    rows: list[MetricRow],
    town_count: int,
    config: dict[str, Any] | None = None,
    scoring: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Share of towns with a usable (present, not suppressed) value per scoring input.

    ``scoring`` is the factor config to report on: readiness v1 unless given."""
    config = config or qa_config()
    scoring = scoring or scoring_config("v1")
    aliases = config["coverage"].get("input_aliases", {})
    usable: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.value is not None and not row.suppressed:
            usable[row.metric].add(row.geoid)
    report: dict[str, float] = {}
    for factor in scoring["factors"].values():
        for name in factor["inputs"]:
            metric = aliases.get(name, name)
            report[name] = len(usable.get(metric, set())) / town_count if town_count else 0.0
    return report


def check_coverage(report: dict[str, float], config: dict[str, Any] | None = None) -> None:
    config = config or qa_config()
    floor = float(config["coverage"]["min_share"])
    conditional = set(config["coverage"].get("conditional_inputs", []))
    short = [
        f"{name}: {share:.0%} of towns (floor {floor:.0%})"
        for name, share in report.items()
        if share < floor and name not in conditional
    ]
    if short:
        raise QAError(short)
