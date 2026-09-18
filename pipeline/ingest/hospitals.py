"""NYS Department of Health facility list (hospitals are filtered in transform)."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from pipeline.ingest.base import fetch_source
from pipeline.storage import RawStore

SOURCE_ID = "hospitals"


def fetch(
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
) -> list[str]:
    return [fetch_source(SOURCE_ID, as_of, store=store, client=client)]


def hospitals_from_csv(data: bytes, description: str = "Hospital") -> list[dict[str, Any]]:
    """Rows of the facility CSV whose Description matches, with float coordinates."""
    import csv
    import io

    out: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(data.decode("utf-8", errors="replace"))):
        if row.get("Description") != description:
            continue
        lat, lon = row.get("Facility Latitude"), row.get("Facility Longitude")
        if not lat or not lon:
            continue
        out.append(
            {
                "facility_id": row["Facility ID"],
                "name": row["Facility Name"],
                "city": row.get("Facility City", ""),
                "county": row.get("Facility County", ""),
                "lat": float(lat),
                "lon": float(lon),
            }
        )
    return out
