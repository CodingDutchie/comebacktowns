"""IRS SOI county-to-county migration: net migration of tax filers for each town's county.

The IRS publishes migration at county level only, so every town carries its county's
figure, named ``county_*`` so the page can say so. The rate is (inflow - outflow)
individuals per 1,000 of the county's year-1 filing population (non-migrants plus
outflow), all from one pair of files; the median across New York's counties is the
momentum benchmark. A suppressed IRS cell (-1) makes the figure missing, never zero.
"""

from __future__ import annotations

import csv
import io
import re
import statistics
from dataclasses import dataclass

from pipeline.transform import Context, MetricRow

SOURCE_ID = "irs"
FILE = re.compile(r"county(inflow|outflow)(\d{2})(\d{2})\.csv$")
TOTAL = ("96", "000")  # "Total Migration-US and Foreign" summary row


@dataclass(frozen=True)
class Flow:
    total: int | None  # individuals (n2) who moved in (inflow file) or out (outflow file)
    stayed: int | None  # individuals who filed from the same county both years


def _n2(value: str) -> int | None:
    n = int(value)
    return None if n < 0 else n  # -1 is the IRS suppression marker


def parse_flows(data: bytes, flow: str, state: str = "36") -> dict[str, Flow]:
    """county fips (3 digits) -> Flow for every county of ``state`` in one file."""
    own, other = ("y2", "y1") if flow == "inflow" else ("y1", "y2")
    totals: dict[str, int | None] = {}
    stayed: dict[str, int | None] = {}
    for row in csv.DictReader(io.StringIO(data.decode("latin-1"))):
        # files before 2022-2023 do not zero-pad the FIPS codes
        if row[f"{own}_statefips"].zfill(2) != state:
            continue
        county = row[f"{own}_countyfips"].zfill(3)
        key = (row[f"{other}_statefips"].zfill(2), row[f"{other}_countyfips"].zfill(3))
        if key == TOTAL:
            totals[county] = _n2(row["n2"])
        elif key == (state, county):
            stayed[county] = _n2(row["n2"])
    return {c: Flow(totals.get(c), stayed.get(c)) for c in totals}


def net_rates(inflow: dict[str, Flow], outflow: dict[str, Flow]) -> dict[str, float]:
    """county -> net migrants per 1,000 of the year-1 filing population."""
    out: dict[str, float] = {}
    for county, arrived in inflow.items():
        left = outflow.get(county)
        if left is None or arrived.total is None or arrived.stayed is None or left.total is None:
            continue
        base = arrived.stayed + left.total
        if base > 0:
            out[county] = 1000 * (arrived.total - left.total) / base
    return out


def year_pairs(keys: list[str]) -> dict[str, dict[str, str]]:
    """'2022-2023' -> {'inflow': key, 'outflow': key} for every complete pair."""
    pairs: dict[str, dict[str, str]] = {}
    for key in keys:
        match = FILE.search(key)
        if match:
            flow, y1, y2 = match.groups()
            pairs.setdefault(f"20{y1}-20{y2}", {})[flow] = key
    return {p: k for p, k in sorted(pairs.items()) if {"inflow", "outflow"} <= set(k)}


def irs_metrics(ctx: Context) -> list[MetricRow]:
    rows: list[MetricRow] = []
    for period, keys in year_pairs(ctx.keys(SOURCE_ID)).items():
        inflow = parse_flows(ctx.store.get_bytes(keys["inflow"]), "inflow")
        outflow = parse_flows(ctx.store.get_bytes(keys["outflow"]), "outflow")
        rates = net_rates(inflow, outflow)
        median = statistics.median(rates.values()) if rates else None
        for town in ctx.towns:
            county = town.county_fips

            def make(
                name: str,
                value: float | None,
                r2_key: str,
                geoid: str = town.geoid,
                period: str = period,
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

            arrived, left = inflow.get(county), outflow.get(county)
            if arrived is not None and arrived.total is not None:
                rows.append(make("county_migration_inflow", arrived.total, keys["inflow"]))
            if left is not None and left.total is not None:
                rows.append(make("county_migration_outflow", left.total, keys["outflow"]))
            if county in rates and median is not None:
                rows.append(make("county_net_migration_rate", rates[county], keys["inflow"]))
                rows.append(make("county_net_migration_rate_ny_median", median, keys["inflow"]))
    return rows
