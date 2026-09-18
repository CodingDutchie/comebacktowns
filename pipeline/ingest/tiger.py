"""TIGERweb incorporated place polygons for the state, as one GeoJSON file."""

from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

import httpx

from pipeline.ingest.base import fetch_url_to_store, source
from pipeline.settings import site_config
from pipeline.storage import RawStore

SOURCE_ID = "tiger"


def query_url() -> str:
    state = site_config()["STATE_FIPS"]
    params = {
        "where": f"STATE='{state}'",
        "outFields": "GEOID,NAME,BASENAME,LSADC,FUNCSTAT,AREALAND,AREAWATER,CENTLAT,CENTLON",
        "outSR": 4326,
        "f": "geojson",
    }
    return f"{source(SOURCE_ID)['url']}?{urlencode(params)}"


def fetch(
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
) -> list[str]:
    state = site_config()["STATE_FIPS"]
    return [
        fetch_url_to_store(
            SOURCE_ID,
            query_url(),
            f"places_{state}.geojson",
            as_of,
            store=store,
            client=client,
        )
    ]
