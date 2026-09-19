"""Scoring: inputs -> curves -> factor scores -> weighted total -> grade or label.

Rules (BUILD_PLAN.md §6): a missing or suppressed input is excluded and lowers coverage,
never scores zero; below ``min_coverage`` there is no grade; readiness grades are curved
within population bands because ACS quality differs sharply between small villages and
cities. The same engine scores momentum (Phase 7) from ``config/momentum.v1.yml``: there the
total is the momentum score and the "grade" is an absolute label (rising, steady, fading),
because momentum measures direction, not rank.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pipeline.scope import Town
from pipeline.score.curves import CONTEXT_ONLY, CURVES, Curve
from pipeline.settings import CONFIG_DIR, load_yaml, scoring_config


@dataclass
class Input:
    """One metric value as used by the score, with its provenance."""

    metric: str
    value: float | None
    period: str | None
    source_id: str | None
    r2_key: str | None
    as_of: str | None
    suppressed: bool
    status: str  # usable | suppressed | missing | not_applicable
    normalised: float | None = None
    contribution: float | None = None  # points of the 0-100 total


@dataclass
class Score:
    """One town's result. ``readiness`` is the 0-100 total of whichever config produced it
    (momentum when scored from config/momentum.*.yml) and ``grade`` its grade or label."""

    geoid: str
    config_version: str
    computed_at: str
    readiness: float
    grade: str | None
    coverage: float
    factor_scores: dict[str, float | None]
    inputs: dict[str, Input]
    band: str = ""
    notes: list[str] = field(default_factory=list)

    def row(self) -> list[Any]:
        return [
            self.geoid,
            self.config_version,
            self.computed_at,
            round(self.readiness, 3),
            self.grade,
            json.dumps(self.factor_scores),
            json.dumps({k: v.__dict__ for k, v in self.inputs.items()}),
            round(self.coverage, 4),
        ]


SCORE_COLUMNS = [
    "geoid",
    "config_version",
    "computed_at",
    "readiness",
    "grade",
    "factor_scores",
    "factor_inputs",
    "coverage",
]

MetricRows = dict[str, dict[str, dict[str, Any]]]  # geoid -> metric -> latest row


def input_aliases() -> dict[str, str]:
    return dict(load_yaml(CONFIG_DIR / "qa.yml")["coverage"].get("input_aliases", {}))


def conditional_inputs() -> set[str]:
    return set(load_yaml(CONFIG_DIR / "qa.yml")["coverage"].get("conditional_inputs", []))


def latest_rows(rows: list[dict[str, Any]]) -> MetricRows:
    """Keep the latest period per (geoid, metric); periods sort lexically within a metric."""
    out: MetricRows = {}
    for row in rows:
        current = out.setdefault(row["geoid"], {}).get(row["metric"])
        if current is None or str(row["period"]) > str(current["period"]):
            out[row["geoid"]][row["metric"]] = row
    return out


def _input(name: str, row: dict[str, Any] | None, conditional: bool) -> Input:
    if row is None or row.get("value") is None:
        status = "not_applicable" if conditional else "missing"
        return Input(name, None, None, None, None, None, False, status)
    suppressed = bool(row.get("suppressed"))
    return Input(
        name,
        float(row["value"]),
        row.get("period"),
        row.get("source_id"),
        row.get("r2_key"),
        row.get("as_of"),
        suppressed,
        "suppressed" if suppressed else "usable",
    )


def score_town(
    town: Town,
    metrics: dict[str, dict[str, Any]],
    *,
    config: dict[str, Any],
    curves: dict[str, Curve],
    scoring_year: int,
    aliases: dict[str, str],
    conditional: set[str],
) -> Score:
    inputs: dict[str, Input] = {}
    factor_scores: dict[str, float | None] = {}
    weighted_sum = 0.0
    weight_used = 0.0
    counted = 0
    usable = 0
    for factor, spec in config["factors"].items():
        names = [n for n in spec["inputs"] if n not in CONTEXT_ONLY]
        context_names = [n for n in spec["inputs"] if n in CONTEXT_ONLY]
        context: dict[str, float] = {"scoring_year": float(scoring_year)}
        for name in context_names:
            row = metrics.get(aliases.get(name, name))
            inp = _input(name, row, False)
            inputs[name] = inp
            if inp.status == "usable" and inp.value is not None:
                context[name] = inp.value
        normalised: list[float] = []
        for name in names:
            row = metrics.get(aliases.get(name, name))
            inp = _input(name, row, name in conditional)
            inputs[name] = inp
            if inp.status != "not_applicable":
                counted += 1
            if inp.status != "usable" or inp.value is None:
                continue
            try:
                inp.normalised = curves[name](inp.value, **context)
            except ValueError:
                inp.status = "missing"  # its context input was unusable
                continue
            usable += 1
            normalised.append(inp.normalised)
        if normalised:
            factor_score = sum(normalised) / len(normalised)
            factor_scores[factor] = round(factor_score, 4)
            weighted_sum += spec["weight"] * factor_score
            weight_used += spec["weight"]
            for name in names:
                inp = inputs[name]
                if inp.normalised is not None:
                    inp.contribution = round(
                        100 * spec["weight"] * inp.normalised / len(normalised), 2
                    )
        else:
            factor_scores[factor] = None
    readiness = 100 * weighted_sum / weight_used if weight_used else 0.0
    coverage = usable / counted if counted else 0.0
    return Score(
        geoid=town.geoid,
        config_version=config["version"],
        computed_at="",
        readiness=readiness,
        grade=None,
        coverage=coverage,
        factor_scores=factor_scores,
        inputs=inputs,
    )


def population_band(town: Town, split: int) -> str:
    pop = town.pop_latest or 0
    return f"under_{split}" if pop < split else f"{split}_plus"


def grade_word(config: dict[str, Any]) -> str:
    return "label" if config["grading"]["method"] == "threshold" else "grade"


def assign_grades(scores: list[Score], towns: dict[str, Town], config: dict[str, Any]) -> None:
    """``curve``: percentile grades within each population band. ``threshold``: absolute
    cut-offs on the total (momentum labels). Either way, nothing below min_coverage."""
    grading = config["grading"]
    if grading["method"] not in {"curve", "threshold"}:
        raise ValueError(f"unsupported grading method {grading['method']}")
    bands = sorted(grading["bands"].items(), key=lambda kv: -kv[1])  # [("A", 90), ...]
    split = int(grading.get("population_band_split", 5000))
    floor = float(config["min_coverage"])
    word = grade_word(config)
    groups: dict[str, list[Score]] = {}
    for score in scores:
        score.band = population_band(towns[score.geoid], split)
        if score.coverage >= floor:
            groups.setdefault(score.band, []).append(score)
        else:
            score.grade = None
            score.notes.append(
                f"no {word}: coverage {score.coverage:.0%} is below the {floor:.0%} floor"
            )
    if grading["method"] == "threshold":
        for members in groups.values():
            for score in members:
                score.grade = next(name for name, cutoff in bands if score.readiness >= cutoff)
        return
    for members in groups.values():
        ranked = sorted(members, key=lambda s: s.readiness)
        n = len(ranked)
        for i, score in enumerate(ranked):
            percentile = 100 * (i + 0.5) / n
            score.grade = next(letter for letter, cutoff in bands if percentile >= cutoff)


def score_all(
    towns: list[Town],
    metric_rows: list[dict[str, Any]],
    *,
    version: str = "v1",
    scoring_year: int | None = None,
    computed_at: str | None = None,
    config: dict[str, Any] | None = None,
    curves: dict[str, Curve] | None = None,
) -> list[Score]:
    """Scores every town. Readiness ``version`` by default; pass ``config`` and ``curves``
    (for example config/momentum.v1.yml with MOMENTUM_CURVES) to score something else."""
    config = config or scoring_config(version)
    curves = curves or CURVES[version]
    aliases = input_aliases()
    conditional = conditional_inputs()
    latest = latest_rows(metric_rows)
    year = scoring_year or datetime.now(UTC).year
    stamp = computed_at or datetime.now(UTC).isoformat(timespec="seconds")
    scores = []
    for town in towns:
        score = score_town(
            town,
            latest.get(town.geoid, {}),
            config=config,
            curves=curves,
            scoring_year=year,
            aliases=aliases,
            conditional=conditional,
        )
        score.computed_at = stamp
        scores.append(score)
    assign_grades(scores, {t.geoid: t for t in towns}, config)
    return scores


def explain(score: Score, town: Town, config: dict[str, Any], curves: dict[str, Curve]) -> str:
    """A complete audit trail for one town: every input, its raw value, curve and points."""
    kind = config.get("kind", "readiness")
    word = grade_word(config)
    how = "absolute cut-offs" if word == "label" else f"curved within population band {score.band}"
    lines = [
        f"{town.name} ({town.legal_type}, {town.county} County, {town.region}) "
        f"— GEOID {town.geoid}",
        f"{kind} {score.readiness:.1f} / 100, {word} {score.grade or 'none'} "
        f"({how}), coverage {score.coverage:.0%}, "
        f"config {kind} {score.config_version}, computed {score.computed_at}",
    ]
    lines.extend(f"  note: {n}" for n in score.notes)
    for factor, spec in config["factors"].items():
        fs = score.factor_scores.get(factor)
        shown = f"{fs:.3f}" if fs is not None else "no usable inputs"
        lines.append(f"\n{factor}  weight {spec['weight']:.2f}  factor score {shown}")
        for name in spec["inputs"]:
            inp = score.inputs[name]
            if inp.status in {"missing", "not_applicable"}:
                lines.append(f"  {name:28s} {inp.status}")
                continue
            raw = f"{inp.value:,.4g}" if inp.value is not None else "-"
            provenance = f"{inp.source_id} {inp.period} {inp.r2_key}"
            if name in CONTEXT_ONLY:
                lines.append(
                    f"  {name:28s} raw {raw:>14s}  (context for another input)  {provenance}"
                )
                continue
            if inp.status == "suppressed":
                lines.append(
                    f"  {name:28s} raw {raw:>14s}  suppressed (MOE > 40%), excluded  {provenance}"
                )
                continue
            lines.append(
                f"  {name:28s} raw {raw:>14s}  normalised {inp.normalised:.3f}  "
                f"contributes {inp.contribution:5.2f} pts  {provenance}"
            )
            lines.append(f"  {'':28s} curve: {curves[name].describe()}")
    return "\n".join(lines)
