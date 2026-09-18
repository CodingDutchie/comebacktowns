"""Write metric rows to D1: idempotent upserts keyed on (geoid, metric, period)."""

from __future__ import annotations

from pipeline.load.d1 import D1Client
from pipeline.transform import METRIC_COLUMNS, MetricRow


def load_metrics(rows: list[MetricRow], d1: D1Client) -> int:
    return d1.upsert(
        "metrics", METRIC_COLUMNS, [r.row() for r in rows], conflict=["geoid", "metric", "period"]
    )
