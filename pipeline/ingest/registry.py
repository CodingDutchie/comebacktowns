"""The feeds the CLI knows about, in build order."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from pipeline.ingest import gazetteer, popest
from pipeline.storage import RawStore

Fetcher = Callable[..., str]

FEEDS: dict[str, Fetcher] = {
    gazetteer.SOURCE_ID: gazetteer.fetch,
    popest.SOURCE_ID: popest.fetch,
}


def fetch_all(as_of: str | date | None, *, store: RawStore | None = None) -> dict[str, str]:
    return {name: fetch(as_of, store=store) for name, fetch in FEEDS.items()}
