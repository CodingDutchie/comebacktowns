"""Population level and 2020-latest change from the popest snapshot, plus the median change
across every New York place in the file, which the momentum score uses as its benchmark."""

from __future__ import annotations

import statistics

import polars as pl

from pipeline.scope import SUMLEV_PLACE, latest_pop_column, read_popest
from pipeline.transform import Context, MetricRow

SOURCE_ID = "popest"
BASE_COL = "POPESTIMATE2020"


def popest_metrics(ctx: Context) -> list[MetricRow]:
    key = ctx.keys(SOURCE_ID)[0]
    frame = read_popest(ctx.store.get_bytes(key)).filter(
        (pl.col("STATE") == "36") & (pl.col("SUMLEV") == SUMLEV_PLACE)
    )
    latest_col, latest_year = latest_pop_column(frame.columns)
    by_place: dict[str, tuple[int | None, int | None]] = {}
    changes: list[float] = []
    for place, latest, base in frame.select("PLACE", latest_col, BASE_COL).iter_rows():
        latest_n = int(latest) if latest not in (None, "") else None
        base_n = int(base) if base not in (None, "") else None
        by_place[place] = (latest_n, base_n)
        if latest_n is not None and base_n:
            changes.append(latest_n / base_n - 1)
    ny_median = statistics.median(changes) if changes else None
    rows: list[MetricRow] = []
    for town in ctx.towns:
        latest_n, base_n = by_place.get(town.geoid[2:], (None, None))

        def make(name: str, period: str, value: float | None, geoid: str = town.geoid) -> MetricRow:
            return MetricRow(
                geoid=geoid,
                metric=name,
                period=period,
                value=value,
                source_id=SOURCE_ID,
                as_of=ctx.as_of_for(SOURCE_ID),
                r2_key=key,
            )

        rows.append(make("population", str(latest_year), latest_n))
        change = latest_n / base_n - 1 if latest_n is not None and base_n else None
        period = f"2020-{latest_year}"
        rows.append(make("population_change", period, change))
        if change is not None and ny_median is not None:
            rows.append(make("population_change_ny_median", period, ny_median))
    return rows
