"""Passenger rail stations: Amtrak (BTS NTAD) and Metro-North (MTA GTFS)."""

from __future__ import annotations

from datetime import date

import httpx

from pipeline.ingest.base import fetch_arcgis_layer, fetch_url_to_store, source
from pipeline.storage import RawStore

SOURCE_ID = "rail"


def fetch(
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
) -> list[str]:
    entry = source(SOURCE_ID)
    amtrak = fetch_arcgis_layer(
        SOURCE_ID,
        entry["amtrak_url"],
        where=entry["amtrak_where"],
        filename="amtrak_stations.json",
        as_of=as_of,
        out_fields="Code,StationName,StnType,StaType,City,State,lat,lon",
        store=store,
        client=client,
    )
    mnr = fetch_url_to_store(
        SOURCE_ID, entry["mnr_url"], "gtfsmnr.zip", as_of, store=store, client=client
    )
    manual = snapshot_manual_stations(entry["manual_stations"], as_of, store=store)
    return [amtrak, mnr, manual]


def snapshot_manual_stations(
    path: str, as_of: str | date | None, *, store: RawStore | None = None
) -> str:
    """Copy the curated station list into R2 next to the feeds so rows can cite it."""
    import hashlib

    from pipeline.ingest.base import normalise_as_of
    from pipeline.settings import ROOT
    from pipeline.storage import raw_key, raw_store, write_meta

    store = store or raw_store()
    key = raw_key(SOURCE_ID, normalise_as_of(as_of), "manual_stations.yml")
    data = (ROOT / path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if store.exists(key):
        return key
    store.put_bytes(key, data, "application/yaml")
    write_meta(
        store,
        key,
        url=f"repo://{path}",
        size=len(data),
        sha256=digest,
        content_type="application/yaml",
    )
    return key
