"""Population level and 2020-2024 change from the popest snapshot."""

from __future__ import annotations

import polars as pl

from pipeline.scope import SUMLEV_PLACE, latest_pop_column, read_popest
from pipeline.transform import Context, MetricRow

SOURCE_ID = "popest"


def popest_metrics(ctx: Context) -> list[MetricRow]:
    key = ctx.keys(SOURCE_ID)[0]
    frame = read_popest(ctx.store.get_bytes(key)).filter(
        (pl.col("STATE") == "36") & (pl.col("SUMLEV") == SUMLEV_PLACE)
    )
    latest_col, latest_year = latest_pop_column(frame.columns)
    base_col = "POPESTIMATE2020"
    by_place = {
        place: (int(latest), int(base) if base not in (None, "") else None)
        for place, latest, base in frame.select("PLACE", latest_col, base_col).iter_rows()
    }
    rows: list[MetricRow] = []
    for town in ctx.towns:
        latest, base = by_place.get(town.geoid[2:], (None, None))
        rows.append(
            MetricRow(
                geoid=town.geoid,
                metric="population",
                period=str(latest_year),
                value=latest,
                source_id=SOURCE_ID,
                as_of=ctx.as_of,
                r2_key=key,
            )
        )
        change = (latest - base) / base if latest is not None and base else None
        rows.append(
            MetricRow(
                geoid=town.geoid,
                metric="population_change",
                period=f"2020-{latest_year}",
                value=change,
                source_id=SOURCE_ID,
                as_of=ctx.as_of,
                r2_key=key,
            )
        )
    return rows
