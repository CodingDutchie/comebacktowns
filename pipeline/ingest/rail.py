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
    return [amtrak, mnr]
