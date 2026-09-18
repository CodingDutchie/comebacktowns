"""Census sub-county population estimates (cities, villages, towns), one national CSV."""

from __future__ import annotations

from datetime import date

import httpx

from pipeline.ingest.base import fetch_source
from pipeline.storage import RawStore

SOURCE_ID = "popest"


def fetch(
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
) -> str:
    return fetch_source(SOURCE_ID, as_of, store=store, client=client)
