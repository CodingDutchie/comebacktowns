"""The feeds the CLI knows about, in build order. Each ``fetch`` returns its R2 keys."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from pipeline.ingest import (
    acs,
    dri,
    gazetteer,
    hospitals,
    irs,
    nrhp,
    osm,
    osrm,
    permits,
    popest,
    rail,
    tiger,
    zillow,
)
from pipeline.storage import RawStore

Fetcher = Callable[..., str | list[str]]

FEEDS: dict[str, Fetcher] = {
    gazetteer.SOURCE_ID: gazetteer.fetch,
    popest.SOURCE_ID: popest.fetch,
    tiger.SOURCE_ID: tiger.fetch,
    acs.SOURCE_ID: acs.fetch,
    permits.SOURCE_ID: permits.fetch,
    nrhp.SOURCE_ID: nrhp.fetch,
    rail.SOURCE_ID: rail.fetch,
    hospitals.SOURCE_ID: hospitals.fetch,
    zillow.SOURCE_ID: zillow.fetch,
    dri.SOURCE_ID: dri.fetch,
    irs.SOURCE_ID: irs.fetch,
    osrm.SOURCE_ID: osrm.fetch,
    osm.SOURCE_ID: osm.fetch,
}


def fetch_one(name: str, as_of: str | date | None, *, store: RawStore | None = None) -> list[str]:
    result = FEEDS[name](as_of, store=store)
    return [result] if isinstance(result, str) else list(result)


def fetch_all(as_of: str | date | None, *, store: RawStore | None = None) -> dict[str, list[str]]:
    return {name: fetch_one(name, as_of, store=store) for name in FEEDS}
