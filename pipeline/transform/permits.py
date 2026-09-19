"""Building Permits Survey: units permitted per year and a 3-year rolling rate per 1,000.

QA rule 2: the headline figure is the mean of the latest three annual files, so a single
large project cannot spike a small town. A year in which the place reported fewer than
twelve months is carried (the Census annual total includes its imputation for the missing
months) but the rolling rate is marked suppressed, which the site shows as such.

For momentum, ``permit_rate_change`` is the latest three-year rate minus the three-year
rate ending two years earlier (five consecutive annual files), in units per 1,000 residents
a year; it is suppressed when any of those five years was short.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from pipeline.transform import Context, MetricRow

SOURCE_ID = "permits"
SHIFT = 2  # years between the two windows compared for momentum
# Column positions in the annual place file (two header rows, then a blank line).
COL_STATE, COL_FIPS_PLACE, COL_CBSA, COL_MONTHS = 1, 5, 9, 15
COL_UNITS = (18, 21, 24, 27)  # 1-unit, 2-unit, 3-4 unit, 5+ unit dwellings permitted


@dataclass
class PermitYear:
    year: int
    units: int
    months_reported: int
    cbsa: str
    r2_key: str


def parse_place_file(data: bytes, state: str = "36") -> dict[str, tuple[int, int, str]]:
    """FIPS place code -> (units, months reported, CBSA code) for one annual file."""
    lines = data.decode("latin-1").splitlines()
    out: dict[str, tuple[int, int, str]] = {}
    for row in csv.reader(io.StringIO("\n".join(lines[3:]))):
        if len(row) < 30 or row[COL_STATE].strip() != state:
            continue
        place = row[COL_FIPS_PLACE].strip()
        if not place or place == "00000":
            continue
        units = sum(int(row[i] or 0) for i in COL_UNITS)
        months = int(row[COL_MONTHS] or 0)
        out[place] = (units, months, row[COL_CBSA].strip())
    return out


def year_of(key: str) -> int:
    match = re.search(r"ne(\d{4})a\.txt$", key)
    if not match:
        raise ValueError(f"unexpected permits key {key}")
    return int(match.group(1))


def load_years(ctx: Context) -> dict[str, list[PermitYear]]:
    """place code -> PermitYear per file, oldest first."""
    years: dict[str, list[PermitYear]] = {}
    for key in sorted(ctx.keys(SOURCE_ID), key=year_of):
        year = year_of(key)
        for place, (units, months, cbsa) in parse_place_file(ctx.store.get_bytes(key)).items():
            years.setdefault(place, []).append(PermitYear(year, units, months, cbsa, key))
    return years


def place_cbsa_codes(ctx: Context) -> dict[str, str]:
    """geoid -> CBSA code from the latest permits file; '99999' (none) is omitted."""
    out: dict[str, str] = {}
    for place, entries in load_years(ctx).items():
        cbsa = entries[-1].cbsa
        if cbsa and cbsa != "99999":
            out["36" + place] = cbsa
    return out


def permits_metrics(ctx: Context, window: int = 3) -> list[MetricRow]:
    years = load_years(ctx)
    rows: list[MetricRow] = []
    for town in ctx.towns:
        entries = years.get(town.geoid[2:], [])
        for entry in entries:
            rows.append(
                MetricRow(
                    geoid=town.geoid,
                    metric="permit_units",
                    period=str(entry.year),
                    value=entry.units,
                    source_id=SOURCE_ID,
                    as_of=ctx.as_of_for(SOURCE_ID),
                    r2_key=entry.r2_key,
                )
            )
            rows.append(
                MetricRow(
                    geoid=town.geoid,
                    metric="permit_months_reported",
                    period=str(entry.year),
                    value=entry.months_reported,
                    source_id=SOURCE_ID,
                    as_of=ctx.as_of_for(SOURCE_ID),
                    r2_key=entry.r2_key,
                )
            )
        recent = entries[-window:]
        if len(recent) < window or not town.pop_latest:
            continue
        per_1k = town.pop_latest / 1000
        mean_units = sum(e.units for e in recent) / window
        period = f"{recent[0].year}-{recent[-1].year}"
        suppressed = int(any(e.months_reported < 12 for e in recent))
        rows.append(
            MetricRow(
                geoid=town.geoid,
                metric="permits_per_1k",
                period=period,
                value=mean_units / per_1k,
                suppressed=suppressed,
                source_id=SOURCE_ID,
                as_of=ctx.as_of_for(SOURCE_ID),
                r2_key=recent[-1].r2_key,
            )
        )
        span = entries[-(window + SHIFT) :]
        consecutive = len(span) == window + SHIFT and all(
            b.year == a.year + 1 for a, b in zip(span, span[1:], strict=False)
        )
        if not consecutive:
            continue
        earlier = span[:window]
        change = (mean_units - sum(e.units for e in earlier) / window) / per_1k
        rows.append(
            MetricRow(
                geoid=town.geoid,
                metric="permit_rate_change",
                period=f"{earlier[0].year}-{earlier[-1].year} to {period}",
                value=change,
                suppressed=int(any(e.months_reported < 12 for e in span)),
                source_id=SOURCE_ID,
                as_of=ctx.as_of_for(SOURCE_ID),
                r2_key=recent[-1].r2_key,
            )
        )
    return rows
