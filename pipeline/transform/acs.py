"""ACS group files -> metrics with margins of error and the 40% suppression rule."""

from __future__ import annotations

import json
import math
from typing import Any

from pipeline.transform import Context, MetricRow, suppress_if_wide

SOURCE_ID = "acs"
SENTINEL_MAX = -222_222_222  # Census API uses large negative codes for N/A and suppressed
VINTAGE = 2024
PRIOR = 2019
PERIOD = "2020-2024"
PRIOR_PERIOD = "2015-2019"
TREND_PERIOD = "2015-2019 to 2020-2024"

GEO_COLUMNS = {
    "place": ("state", "place"),
    "county": ("state", "county"),
    "cbsa": ("metropolitan statistical area/micropolitan statistical area",),
    "state": ("state",),
}


def _num(text: Any) -> float | None:
    if text is None or text == "":
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return None if value <= SENTINEL_MAX else value


def load_group(data: bytes, geography: str) -> dict[str, dict[str, float | None]]:
    """GEOID -> {variable: value}. Geography columns are concatenated into the GEOID."""
    payload = json.loads(data)
    header, rows = payload[0], payload[1:]
    index = {name: i for i, name in enumerate(header)}
    geo_cols = [index[c] for c in GEO_COLUMNS[geography]]
    out: dict[str, dict[str, float | None]] = {}
    for row in rows:
        geoid = "".join(str(row[i]) for i in geo_cols)
        out[geoid] = {
            name: _num(row[i])
            for name, i in index.items()
            if name[-1] in "EM" and not name.endswith(("EA", "MA")) and name != "NAME"
        }
    return out


def estimate(vars_: dict[str, float | None], var: str) -> tuple[float | None, float | None]:
    return vars_.get(f"{var}E"), vars_.get(f"{var}M")


def total(vars_: dict[str, float | None], names: list[str]) -> tuple[float | None, float | None]:
    """Sum of estimates; MOE of a sum is the root sum of squares of the parts."""
    values, moes = [], []
    for name in names:
        value, moe = estimate(vars_, name)
        if value is None:
            return None, None
        values.append(value)
        moes.append(moe if moe is not None else 0.0)
    return sum(values), math.sqrt(sum(m * m for m in moes))


def ratio(
    vars_: dict[str, float | None], numerators: list[str], denominator: str
) -> tuple[float | None, float | None]:
    """Census proportion formula: MOE = sqrt(MOE_n^2 - p^2 MOE_d^2) / d, ratio form if negative."""
    num, num_moe = total(vars_, numerators)
    den, den_moe = estimate(vars_, denominator)
    if num is None or den is None or den == 0:
        return None, None
    p = num / den
    den_moe = den_moe or 0.0
    num_moe = num_moe or 0.0
    inner = num_moe**2 - (p**2) * den_moe**2
    if inner < 0:
        inner = num_moe**2 + (p**2) * den_moe**2
    return p, math.sqrt(inner) / den


# metric name -> (table, kind, numerators, denominator)
PLACE_METRICS: dict[str, tuple[str, str, list[str], str | None]] = {
    "median_home_value": ("B25077", "estimate", ["B25077_001"], None),
    "median_gross_rent": ("B25064", "estimate", ["B25064_001"], None),
    "median_household_income": ("B19013", "estimate", ["B19013_001"], None),
    "vacancy_rate": ("B25002", "ratio", ["B25002_003"], "B25002_001"),
    "pre1940_share": ("B25034", "ratio", ["B25034_011"], "B25034_001"),
    "broadband_subscription_share": ("B28002", "ratio", ["B28002_007"], "B28002_001"),
    "poverty_rate": ("B17001", "ratio", ["B17001_002"], "B17001_001"),
    "commute_60plus_share": ("B08303", "ratio", ["B08303_012", "B08303_013"], "B08303_001"),
    "k12_enrollment": (
        "B14001",
        "total",
        ["B14001_003", "B14001_004", "B14001_005", "B14001_006", "B14001_007"],
        None,
    ),
    "population_under_18": ("B09001", "estimate", ["B09001_001"], None),
    "population_total": ("B01003", "estimate", ["B01003_001"], None),
}
SHARES = {  # metric -> (numerator metric, denominator metric), across tables
    "under_18_share": ("population_under_18", "population_total"),
}
TRENDS = {  # metric -> base metric whose 2015-2019 vs 2020-2024 change is reported
    "school_enrollment_trend": "k12_enrollment",
    "under_18_trend": "population_under_18",
}


def proportion(
    num: float | None, num_moe: float | None, den: float | None, den_moe: float | None
) -> tuple[float | None, float | None]:
    """The proportion formula on two already-extracted estimates."""
    if num is None or den is None or den == 0:
        return None, None
    p = num / den
    inner = (num_moe or 0.0) ** 2 - (p**2) * (den_moe or 0.0) ** 2
    if inner < 0:
        inner = (num_moe or 0.0) ** 2 + (p**2) * (den_moe or 0.0) ** 2
    return p, math.sqrt(inner) / den


def compute(
    vars_: dict[str, float | None], kind: str, numerators: list[str], denominator: str | None
) -> tuple[float | None, float | None]:
    if kind == "estimate":
        return estimate(vars_, numerators[0])
    if kind == "total":
        return total(vars_, numerators)
    assert denominator is not None
    return ratio(vars_, numerators, denominator)


def _rows_for_level(
    ctx: Context,
    year: int,
    period: str,
    metrics: dict[str, tuple[str, str, list[str], str | None]],
) -> dict[str, dict[str, tuple[float | None, float | None, str]]]:
    """geoid -> metric -> (value, moe, r2_key) at place level for one vintage."""
    out: dict[str, dict[str, tuple[float | None, float | None, str]]] = {
        t.geoid: {} for t in ctx.towns
    }
    by_table: dict[str, list[str]] = {}
    for metric, (table, *_rest) in metrics.items():
        by_table.setdefault(table, []).append(metric)
    for table, metric_names in by_table.items():
        key = ctx.key(SOURCE_ID, f"acs5_{year}_{table}_place.json")
        data = load_group(ctx.store.get_bytes(key), "place")
        for geoid in out:
            vars_ = data.get(geoid)
            for metric in metric_names:
                _, kind, numerators, denominator = metrics[metric]
                if vars_ is None:
                    out[geoid][metric] = (None, None, key)
                    continue
                value, moe = compute(vars_, kind, numerators, denominator)
                out[geoid][metric] = (value, moe, key)
    return out


def cbsa_lookup(ctx: Context) -> dict[str, str]:
    """geoid -> CBSA code, from the Building Permits Survey place file (its own crosswalk)."""
    from pipeline.transform.permits import place_cbsa_codes

    return place_cbsa_codes(ctx)


def acs_metrics(ctx: Context) -> list[MetricRow]:
    rows: list[MetricRow] = []
    latest = _rows_for_level(ctx, VINTAGE, PERIOD, PLACE_METRICS)
    prior_metrics = {m: PLACE_METRICS[m] for m in TRENDS.values()}
    prior = _rows_for_level(ctx, PRIOR, PRIOR_PERIOD, prior_metrics)

    for geoid, metrics in latest.items():
        for metric, (value, moe, key) in metrics.items():
            rows.append(
                MetricRow(
                    geoid=geoid,
                    metric=metric,
                    period=PERIOD,
                    value=value,
                    moe=moe,
                    suppressed=suppress_if_wide(value, moe),
                    source_id=SOURCE_ID,
                    as_of=ctx.as_of_for(SOURCE_ID),
                    r2_key=key,
                )
            )
        for share, (num_name, den_name) in SHARES.items():
            num_v, num_m, key = metrics[num_name]
            den_v, den_m, _ = metrics[den_name]
            value, moe = proportion(num_v, num_m, den_v, den_m)
            rows.append(
                MetricRow(
                    geoid=geoid,
                    metric=share,
                    period=PERIOD,
                    value=value,
                    moe=moe,
                    suppressed=suppress_if_wide(value, moe),
                    source_id=SOURCE_ID,
                    as_of=ctx.as_of_for(SOURCE_ID),
                    r2_key=key,
                )
            )
        for trend, base in TRENDS.items():
            now_v, now_m, key = metrics[base]
            then_v, then_m, _ = prior[geoid][base]
            if now_v is None or then_v is None or then_v == 0:
                value, moe = None, None
            else:
                value = (now_v - then_v) / then_v
                # MOE of a ratio of two independent estimates, expressed on the change
                q = now_v / then_v
                moe = math.sqrt((now_m or 0) ** 2 + (q**2) * (then_m or 0) ** 2) / then_v
            rows.append(
                MetricRow(
                    geoid=geoid,
                    metric=trend,
                    period=TREND_PERIOD,
                    value=value,
                    moe=moe,
                    suppressed=suppress_if_wide(value, moe),
                    source_id=SOURCE_ID,
                    as_of=ctx.as_of_for(SOURCE_ID),
                    r2_key=key,
                )
            )

    # County and metro (CBSA) medians, attached to each town for price headroom.
    county_key = ctx.key(SOURCE_ID, f"acs5_{VINTAGE}_B25077_county.json")
    counties = load_group(ctx.store.get_bytes(county_key), "county")
    cbsa_key = ctx.key(SOURCE_ID, f"acs5_{VINTAGE}_B25077_cbsa.json")
    cbsas = load_group(ctx.store.get_bytes(cbsa_key), "cbsa")
    cbsa_of = cbsa_lookup(ctx)
    for town in ctx.towns:
        county_vars = counties.get("36" + town.county_fips)
        c_value, c_moe = estimate(county_vars, "B25077_001") if county_vars else (None, None)
        rows.append(
            MetricRow(
                geoid=town.geoid,
                metric="county_median_home_value",
                period=PERIOD,
                value=c_value,
                moe=c_moe,
                suppressed=suppress_if_wide(c_value, c_moe),
                source_id=SOURCE_ID,
                as_of=ctx.as_of_for(SOURCE_ID),
                r2_key=county_key,
            )
        )
        cbsa_code = cbsa_of.get(town.geoid)
        cbsa_vars = cbsas.get(cbsa_code) if cbsa_code else None
        if cbsa_vars is not None:
            m_value, m_moe = estimate(cbsa_vars, "B25077_001")
            m_key = cbsa_key
            rows.append(
                MetricRow(
                    geoid=town.geoid,
                    metric="cbsa_median_home_value",
                    period=PERIOD,
                    value=m_value,
                    moe=m_moe,
                    suppressed=suppress_if_wide(m_value, m_moe),
                    source_id=SOURCE_ID,
                    as_of=ctx.as_of_for(SOURCE_ID),
                    r2_key=cbsa_key,
                )
            )
        else:
            m_value, m_moe, m_key = c_value, c_moe, county_key
        rows.append(
            MetricRow(
                geoid=town.geoid,
                metric="metro_median_home_value",
                period=PERIOD,
                value=m_value,
                moe=m_moe,
                suppressed=suppress_if_wide(m_value, m_moe),
                source_id=SOURCE_ID,
                as_of=ctx.as_of_for(SOURCE_ID),
                r2_key=m_key,
            )
        )
    return rows
