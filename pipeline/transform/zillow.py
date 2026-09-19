"""Zillow ZHVI / ZORI: the latest month with a value and its one-year change, matched on
name and county.

A place Zillow does not cover simply gets no row. That is a gap, never a zero. The
one-year change is paired with the median change across every New York place in the same
file (``*_change_1y_ny_median``), which the momentum score uses as its benchmark, so a
statewide boom does not read as momentum in every town.
"""

from __future__ import annotations

import io
import re
import statistics
from dataclasses import dataclass

import polars as pl

from pipeline.transform import Context, MetricRow

SOURCE_ID = "zillow"
FILES = {"zhvi": "zhvi_city.csv", "zori": "zori_city.csv"}
MONTH = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Latest:
    period: str  # YYYY-MM of the latest month with a value
    value: float
    change_1y: float | None  # value over the value twelve months earlier, minus 1


def read_places(data: bytes, state: str = "NY") -> dict[tuple[str, str], Latest]:
    """(RegionName, CountyName) -> latest value and one-year change for every place in the state."""
    frame = pl.read_csv(io.BytesIO(data), infer_schema_length=0).filter(pl.col("State") == state)
    months = [c for c in frame.columns if MONTH.match(c)]
    out: dict[tuple[str, str], Latest] = {}
    for row in frame.select(["RegionName", "CountyName", *months]).iter_rows():
        name, county, *raw = row
        values = [float(v) if v not in (None, "") else None for v in raw]
        idx = next((i for i in range(len(values) - 1, -1, -1) if values[i] is not None), None)
        if idx is None:
            continue
        latest = values[idx]
        prior = values[idx - 12] if idx >= 12 else None
        change = latest / prior - 1 if prior and latest is not None else None
        out[(name, county)] = Latest(months[idx][:7], latest, change)  # type: ignore[arg-type]
    return out


def latest_values(data: bytes, state: str = "NY") -> dict[tuple[str, str], tuple[str, float]]:
    """(RegionName, CountyName) -> (period YYYY-MM, value) from the last non-null month."""
    return {k: (v.period, v.value) for k, v in read_places(data, state).items()}


def ny_median_change(places: dict[tuple[str, str], Latest]) -> float | None:
    """The median one-year change across every place in the file that has one."""
    changes = [p.change_1y for p in places.values() if p.change_1y is not None]
    return statistics.median(changes) if changes else None


def zillow_metrics(ctx: Context) -> list[MetricRow]:
    rows: list[MetricRow] = []
    for metric, filename in FILES.items():
        key = ctx.key(SOURCE_ID, filename)
        places = read_places(ctx.store.get_bytes(key))
        median = ny_median_change(places)
        file_period = max((p.period for p in places.values()), default="")
        for town in ctx.towns:
            hit = places.get((town.name, f"{town.county} County"))
            if hit is None:
                continue

            def make(
                name: str, period: str, value: float, geoid: str = town.geoid, r2_key: str = key
            ) -> MetricRow:
                return MetricRow(
                    geoid=geoid,
                    metric=name,
                    period=period,
                    value=value,
                    source_id=SOURCE_ID,
                    as_of=ctx.as_of_for(SOURCE_ID),
                    r2_key=r2_key,
                )

            rows.append(make(metric, hit.period, hit.value))
            if hit.change_1y is None or median is None:
                continue
            rows.append(make(f"{metric}_change_1y", hit.period, hit.change_1y))
            rows.append(make(f"{metric}_change_1y_ny_median", file_period, median))
    return rows
