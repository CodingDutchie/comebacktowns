"""Scope checks: every town has coordinates and a unique slug, and the count is plausible."""

from __future__ import annotations

from collections import Counter
from typing import Any

from pipeline.qa import QAError
from pipeline.scope import Town


def validate_towns(towns: list[Town], scope: dict[str, Any]) -> None:
    problems: list[str] = []
    expected = scope.get("expected_count", {})
    lo, hi = int(expected.get("min", 1)), int(expected.get("max", 10_000))
    if not (lo <= len(towns) <= hi):
        problems.append(f"{len(towns)} towns in scope, expected between {lo} and {hi}")
    for label, counter in (
        ("geoid", Counter(t.geoid for t in towns)),
        ("slug", Counter(t.slug for t in towns)),
    ):
        dupes = sorted(k for k, n in counter.items() if n > 1)
        if dupes:
            problems.append(f"duplicate {label}: {dupes}")
    for town in towns:
        if not (40.0 <= town.lat <= 45.1 and -80.0 <= town.lon <= -71.7):
            problems.append(f"{town.slug}: coordinates {town.lat},{town.lon} are outside New York")
        if not town.slug or not town.slug.endswith("-ny"):
            problems.append(f"{town.geoid}: bad slug {town.slug!r}")
        if town.pop_latest is None:
            problems.append(f"{town.slug}: no population")
    if problems:
        raise QAError(problems)
