"""Zillow ZHVI / ZORI: the latest month with a value, matched on name and county.

A place Zillow does not cover simply gets no row. That is a gap, never a zero.
"""

from __future__ import annotations

import io
import re

import polars as pl

from pipeline.transform import Context, MetricRow

SOURCE_ID = "zillow"
FILES = {"zhvi": "zhvi_city.csv", "zori": "zori_city.csv"}
MONTH = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def latest_values(data: bytes, state: str = "NY") -> dict[tuple[str, str], tuple[str, float]]:
    """(RegionName, CountyName) -> (period YYYY-MM, value) from the last non-null month."""
    frame = pl.read_csv(io.BytesIO(data), infer_schema_length=0).filter(pl.col("State") == state)
    months = [c for c in frame.columns if MONTH.match(c)]
    out: dict[tuple[str, str], tuple[str, float]] = {}
    for row in frame.select(["RegionName", "CountyName", *months]).iter_rows():
        name, county, *values = row
        for month, value in zip(reversed(months), reversed(values), strict=True):
            if value not in (None, ""):
                out[(name, county)] = (month[:7], float(value))
                break
    return out


def zillow_metrics(ctx: Context) -> list[MetricRow]:
    rows: list[MetricRow] = []
    for metric, filename in FILES.items():
        key = ctx.key(SOURCE_ID, filename)
        values = latest_values(ctx.store.get_bytes(key))
        for town in ctx.towns:
            hit = values.get((town.name, f"{town.county} County"))
            if hit is None:
                continue
            period, value = hit
            rows.append(
                MetricRow(
                    geoid=town.geoid,
                    metric=metric,
                    period=period,
                    value=value,
                    source_id=SOURCE_ID,
                    as_of=ctx.as_of_for(SOURCE_ID),
                    r2_key=key,
                )
            )
    return rows
