"""Zillow ZHVI and ZORI city-level bulk CSVs. Large: streamed straight to R2."""

from __future__ import annotations

from datetime import date

import httpx

from pipeline.ingest.base import fetch_url_to_store, source
from pipeline.storage import RawStore

SOURCE_ID = "zillow"


def fetch(
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
) -> list[str]:
    entry = source(SOURCE_ID)
    return [
        fetch_url_to_store(SOURCE_ID, url, f"{name}_city.csv", as_of, store=store, client=client)
        for name, url in entry["files"].items()
    ]
