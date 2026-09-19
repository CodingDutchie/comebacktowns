"""IRS Statistics of Income county-to-county migration, one inflow and one outflow CSV per
filing-year pair. County level is the finest the IRS publishes.

``years`` in config/sources.yml is the floor; the next filing-year pair is probed on every
fetch and pulled once both of its files exist (``discover_ahead`` caps the look-ahead).
"""

from __future__ import annotations

import logging
from datetime import date

import httpx

from pipeline.http import exists, make_client
from pipeline.ingest.base import extend_years, fetch_url_to_store, source
from pipeline.storage import RawStore

log = logging.getLogger(__name__)

SOURCE_ID = "irs"


def filename(flow: str, years: str) -> str:
    return f"county{flow}{years}.csv"


def next_pair(years: str) -> str:
    """'2223' (2022 to 2023) -> '2324'."""
    y2 = int(years[2:])
    return f"{y2:02d}{(y2 + 1) % 100:02d}"


def discover(client: httpx.Client | None = None) -> list[str]:
    """Filing-year pairs beyond the configured list whose inflow and outflow files both exist."""
    entry = source(SOURCE_ID)
    own = client is None
    client = client or make_client()
    try:
        found = extend_years(
            list(entry["years"]),
            next_pair,
            lambda p: all(
                exists(client, entry["url"].format(flow=f, years=p)) for f in entry["flows"]
            ),
            int(entry.get("discover_ahead", 0)),
        )
    finally:
        if own:
            client.close()
    if found:
        log.info("%s: new year pair(s) published: %s", SOURCE_ID, ", ".join(found))
    return found


def fetch(
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
) -> list[str]:
    entry = source(SOURCE_ID)
    own = client is None
    client = client or make_client()
    keys = []
    try:
        for years in [*entry["years"], *discover(client)]:
            for flow in entry["flows"]:
                url = entry["url"].format(flow=flow, years=years)
                keys.append(
                    fetch_url_to_store(
                        SOURCE_ID, url, filename(flow, years), as_of, store=store, client=client
                    )
                )
    finally:
        if own:
            client.close()
    return keys
