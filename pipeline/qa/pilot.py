"""QA rule 4: the hand-scored pilot towns must land within ±3 points of the engine."""

from __future__ import annotations

import csv
from pathlib import Path

from pipeline.qa import QAError
from pipeline.score.engine import Score
from pipeline.settings import ROOT

PILOT_PATH = ROOT / "seed" / "pilot_v0.csv"
TOLERANCE = 3.0


class PilotFixtureMissingError(QAError):
    pass


def load_pilot(path: Path = PILOT_PATH) -> dict[str, float]:
    """geoid or slug -> hand-scored readiness."""
    shown = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    if not path.exists():
        raise PilotFixtureMissingError(
            [f"{shown} is missing: the owner must add the 20 hand-scored towns"]
        )
    out: dict[str, float] = {}
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            key = (row.get("geoid") or row.get("slug") or "").strip()
            if not key:
                continue
            out[key] = float(row["readiness"])
    if not out:
        raise PilotFixtureMissingError([f"{shown} has no rows"])
    return out


def check_pilot(scores: list[Score], slugs: dict[str, str], pilot: dict[str, float]) -> list[str]:
    """Returns the comparison lines; raises QAError when any town drifts beyond tolerance."""
    by_geoid = {s.geoid: s for s in scores}
    by_slug = {slugs[g]: s for g, s in by_geoid.items() if g in slugs}
    lines: list[str] = []
    problems: list[str] = []
    out_of_scope: list[str] = []
    for key, expected in pilot.items():
        score = by_geoid.get(key) or by_slug.get(key)
        if score is None:
            out_of_scope.append(key)
            continue
        drift = score.readiness - expected
        lines.append(
            f"{key:24s} pilot {expected:5.1f}  engine {score.readiness:5.1f}  drift {drift:+5.1f}"
        )
        if abs(drift) > TOLERANCE:
            problems.append(f"{key}: drift {drift:+.1f} exceeds ±{TOLERANCE:g}")
    if out_of_scope:
        lines.append(f"not in the v1 scope, skipped: {', '.join(out_of_scope)}")
    if not lines or all(line.startswith("not in") for line in lines):
        problems.append("no pilot town is in scope")
    if problems:
        raise QAError(problems)
    return lines
