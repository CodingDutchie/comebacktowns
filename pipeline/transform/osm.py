"""OpenStreetMap storefront businesses inside the place, absolute and per 1,000 residents."""

from __future__ import annotations

import json

from pipeline.transform import Context, MetricRow

SOURCE_ID = "osm"


def business_count(document: dict) -> int:
    return sum(1 for e in document.get("elements", []) if e.get("tags"))


def osm_metrics(ctx: Context) -> list[MetricRow]:
    keys = set(ctx.keys(SOURCE_ID))
    period = ctx.as_of[:7]
    rows: list[MetricRow] = []
    for town in ctx.towns:
        key = f"raw/{SOURCE_ID}/{ctx.as_of}/{town.geoid}.json"
        if key not in keys:
            continue
        count = business_count(json.loads(ctx.store.get_bytes(key)))
        rows.append(
            MetricRow(
                geoid=town.geoid,
                metric="osm_business_count",
                period=period,
                value=count,
                source_id=SOURCE_ID,
                as_of=ctx.as_of,
                r2_key=key,
            )
        )
        if town.pop_latest:
            rows.append(
                MetricRow(
                    geoid=town.geoid,
                    metric="osm_business_per_1k",
                    period=period,
                    value=count / (town.pop_latest / 1000),
                    source_id=SOURCE_ID,
                    as_of=ctx.as_of,
                    r2_key=key,
                )
            )
    return rows
