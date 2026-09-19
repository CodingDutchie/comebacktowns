"""IRS Statistics of Income county-to-county migration, one inflow and one outflow CSV per
filing-year pair. County level is the finest the IRS publishes."""

from __future__ import annotations

from datetime import date

import httpx

from pipeline.ingest.base import fetch_url_to_store, source
from pipeline.storage import RawStore

SOURCE_ID = "irs"


def filename(flow: str, years: str) -> str:
    return f"county{flow}{years}.csv"


def fetch(
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
) -> list[str]:
    entry = source(SOURCE_ID)
    keys = []
    for years in entry["years"]:
        for flow in entry["flows"]:
            url = entry["url"].format(flow=flow, years=years)
            keys.append(
                fetch_url_to_store(
                    SOURCE_ID, url, filename(flow, years), as_of, store=store, client=client
                )
            )
    return keys
