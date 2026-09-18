"""National Register historic districts in New York, from the NPS map service."""

from __future__ import annotations

from datetime import date

import httpx

from pipeline.ingest.base import fetch_arcgis_layer, source
from pipeline.storage import RawStore

SOURCE_ID = "nrhp"


def fetch(
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
) -> list[str]:
    entry = source(SOURCE_ID)
    keys = []
    for name, layer in entry["layers"].items():
        keys.append(
            fetch_arcgis_layer(
                SOURCE_ID,
                f"{entry['url']}/{layer}/query",
                where=entry["where"],
                filename=f"ny_districts_{name}.json",
                as_of=as_of,
                out_fields="NRIS_Refnum,RESNAME,ResType,City,County,State,CertDate,Is_NHL",
                store=store,
                client=client,
            )
        )
    return keys
