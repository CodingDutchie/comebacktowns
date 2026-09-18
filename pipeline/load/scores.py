"""Write scores to D1. Each run adds a new computed_at; nothing is overwritten."""

from __future__ import annotations

from typing import Any

from pipeline.load.d1 import D1Client
from pipeline.score.engine import SCORE_COLUMNS, Score


def load_scores(scores: list[Score], d1: D1Client) -> int:
    return d1.upsert(
        "scores",
        SCORE_COLUMNS,
        [s.row() for s in scores],
        conflict=["geoid", "config_version", "computed_at"],
    )


def read_metrics(d1: D1Client) -> list[dict[str, Any]]:
    columns = "geoid, metric, period, value, moe, suppressed, source_id, as_of, r2_key"
    return d1.query(f"SELECT {columns} FROM metrics")  # noqa: S608


def read_towns(d1: D1Client) -> list[dict[str, Any]]:
    return d1.query("SELECT * FROM towns ORDER BY geoid")
