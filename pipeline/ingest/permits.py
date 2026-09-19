"""Census Building Permits Survey, annual place-level files for the Northeast region.

``years`` in config/sources.yml is the floor; the next annual files are probed on every
fetch and pulled when the Census has published them (``discover_ahead`` caps the look-ahead).
"""

from __future__ import annotations

import logging
from datetime import date

import httpx

from pipeline.http import exists, make_client
from pipeline.ingest.base import extend_years, fetch_url_to_store, source
from pipeline.storage import RawStore

log = logging.getLogger(__name__)

SOURCE_ID = "permits"


def discover(client: httpx.Client | None = None) -> list[int]:
    """Years beyond the configured list that the Census has published."""
    entry = source(SOURCE_ID)
    own = client is None
    client = client or make_client()
    try:
        found = extend_years(
            [int(y) for y in entry["years"]],
            lambda y: y + 1,
            lambda y: exists(client, entry["url"].format(year=y)),
            int(entry.get("discover_ahead", 0)),
        )
    finally:
        if own:
            client.close()
    if found:
        log.info("%s: new year(s) published: %s", SOURCE_ID, ", ".join(map(str, found)))
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
        for year in [*entry["years"], *discover(client)]:
            url = entry["url"].format(year=year)
            keys.append(
                fetch_url_to_store(
                    SOURCE_ID, url, f"ne{year}a.txt", as_of, store=store, client=client
                )
            )
    finally:
        if own:
            client.close()
    return keys
