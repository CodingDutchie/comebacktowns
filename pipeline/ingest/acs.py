"""ACS 5-year tables for every place, county and CBSA, via the Census API.

Requests are batched by geography level (all places in the state in one call), never per
town. The key is read from CENSUS_API_KEY and never logged: the stored request URL and log
lines carry ``key=REDACTED``.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from urllib.parse import urlencode

import httpx

from pipeline.http import get, make_client
from pipeline.ingest.base import Throttle, normalise_as_of, put_json, source
from pipeline.settings import redact_url, require_env, site_config
from pipeline.storage import RawStore, raw_key, raw_store

log = logging.getLogger(__name__)

SOURCE_ID = "acs"


def geography_params(geo: dict[str, str], state: str) -> dict[str, str]:
    params = {"for": geo["for"].format(state=state)}
    if "in" in geo:
        params["in"] = geo["in"].format(state=state)
    return params


def plan_requests(entry: dict[str, Any], state: str) -> list[tuple[int, str, str, dict[str, str]]]:
    """(year, table, geography name, geography params) for every file to fetch."""
    latest = int(entry["vintage"])
    prior = int(entry["prior_vintage"])
    requests: list[tuple[int, str, str, dict[str, str]]] = []
    for table in entry["tables"]:
        for geo_name, geo in entry["geographies"].items():
            requests.append((latest, table, geo_name, geography_params(geo, state)))
    for table in entry["prior_tables"]:
        for geo_name, geo in entry["geographies"].items():
            if geo_name == "cbsa":
                continue
            requests.append((prior, table, geo_name, geography_params(geo, state)))
    return requests


def validate_payload(payload: Any, table: str) -> None:
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[0], list):
        raise RuntimeError(f"acs: unexpected response shape for {table}")
    header = payload[0]
    if not any(str(h).startswith(table) for h in header):
        raise RuntimeError(f"acs: response for {table} carries no {table} columns")


def fetch(
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
    sleep: Any = None,
) -> list[str]:
    entry = source(SOURCE_ID)
    key_value: str | None = None  # read lazily: a fully cached run needs no key
    state = site_config()["STATE_FIPS"]
    as_of_str = normalise_as_of(as_of)
    store = store or raw_store()
    own_client = client is None
    client = client or make_client()
    throttle = Throttle(0.5, sleep=sleep) if sleep else Throttle(0.5)
    keys: list[str] = []
    try:
        for year, table, geo_name, geo_params in plan_requests(entry, state):
            key = raw_key(SOURCE_ID, as_of_str, f"acs5_{year}_{table}_{geo_name}.json")
            keys.append(key)
            if store.exists(key):
                log.info("acs: %s already present, skipping", key)
                continue
            key_value = key_value or require_env(entry["requires_key"])
            base = entry["url"].format(year=year)
            public_params = {"get": f"group({table})", **geo_params}
            public_url = f"{base}?{urlencode(public_params)}"
            throttle.wait()
            log.info("acs: fetching %s", redact_url(public_url))
            response = get(client, base, params={**public_params, "key": key_value})
            if response.status_code == 204 or not response.content:
                raise RuntimeError(f"acs: empty response for {table} {geo_name} {year}")
            payload = response.json()
            validate_payload(payload, table)
            put_json(store, key, payload, url=public_url)
            log.info("acs: stored %s (%d rows)", key, len(payload) - 1)
    finally:
        if own_client:
            client.close()
    return keys
