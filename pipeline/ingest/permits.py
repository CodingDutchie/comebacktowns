"""Census Building Permits Survey, annual place-level files for the Northeast region."""

from __future__ import annotations

from datetime import date

import httpx

from pipeline.ingest.base import fetch_url_to_store, source
from pipeline.storage import RawStore

SOURCE_ID = "permits"


def fetch(
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
) -> list[str]:
    entry = source(SOURCE_ID)
    keys = []
    for year in entry["years"]:
        url = entry["url"].format(year=year)
        keys.append(
            fetch_url_to_store(SOURCE_ID, url, f"ne{year}a.txt", as_of, store=store, client=client)
        )
    return keys
