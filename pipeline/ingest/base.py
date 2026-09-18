"""Shared fetch logic: idempotent, streaming, dated keys, polite pacing."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import httpx

from pipeline.http import HashingReader, get, make_client, stream_get
from pipeline.settings import redact_url, sources_config
from pipeline.storage import RawStore, raw_key, raw_store, write_meta

log = logging.getLogger(__name__)


def today() -> str:
    return datetime.now(UTC).date().isoformat()


def normalise_as_of(as_of: str | date | None) -> str:
    if as_of is None:
        return today()
    if isinstance(as_of, date):
        return as_of.isoformat()
    return date.fromisoformat(as_of).isoformat()


def source(source_id: str) -> dict[str, Any]:
    try:
        entry: dict[str, Any] = sources_config()[source_id]
    except KeyError as exc:
        raise KeyError(f"{source_id} is not defined in config/sources.yml") from exc
    return entry


class Throttle:
    """Keeps at least ``min_interval`` seconds between calls to ``wait()``."""

    def __init__(
        self,
        min_interval: float,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            remaining = self.min_interval - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last = now


def fetch_url_to_store(
    source_id: str,
    url: str,
    filename: str,
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
) -> str:
    """Stream ``url`` into ``raw/{source_id}/{as_of}/{filename}`` unless it is already there.

    Returns the key. A second call for the same key is a no-op, which is what makes a rerun
    of ``ingest --all`` safe.
    """
    as_of_str = normalise_as_of(as_of)
    store = store or raw_store()
    key = raw_key(source_id, as_of_str, filename)
    if store.exists(key):
        log.info("%s: %s already present, skipping", source_id, key)
        return key

    log.info("%s: fetching %s -> %s", source_id, redact_url(url), key)
    own_client = client is None
    client = client or make_client()
    captured: dict[str, Any] = {}

    def sink(reader: HashingReader, content_type: str | None) -> None:
        captured["content_type"] = content_type
        store.put(key, reader, content_type)

    try:
        size, digest = stream_get(client, url, sink)
    finally:
        if own_client:
            client.close()
    write_meta(
        store, key, url=url, size=size, sha256=digest, content_type=captured.get("content_type")
    )
    log.info("%s: stored %s (%d bytes, sha256 %s)", source_id, key, size, digest[:12])
    return key


def fetch_source(
    source_id: str,
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
) -> str:
    """Fetch a single-file source described in config/sources.yml."""
    entry = source(source_id)
    return fetch_url_to_store(
        source_id, entry["url"], entry["filename"], as_of, store=store, client=client
    )


def put_json(store: RawStore, key: str, payload: Any, *, url: str) -> None:
    """Store a JSON document plus its sidecar; used for API responses assembled in memory."""
    data = json.dumps(payload, separators=(",", ":")).encode()
    store.put_bytes(key, data, "application/json")
    import hashlib

    write_meta(
        store,
        key,
        url=url,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        content_type="application/json",
    )


def get_json(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> Any:
    """GET a JSON document with retries. ArcGIS-style ``{"error": ...}`` bodies raise."""
    response = get(client, url, params=params)
    payload = response.json()
    if isinstance(payload, dict) and "error" in payload:
        raise RuntimeError(f"{redact_url(str(response.url))}: {payload['error']}")
    return payload


def fetch_arcgis_layer(
    source_id: str,
    url: str,
    *,
    where: str,
    filename: str,
    as_of: str | date | None = None,
    out_fields: str = "*",
    geometry: bool = True,
    out_sr: int = 4326,
    page_size: int = 1000,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
) -> str:
    """Page through an ArcGIS REST layer query and store all features as one JSON file."""
    as_of_str = normalise_as_of(as_of)
    store = store or raw_store()
    key = raw_key(source_id, as_of_str, filename)
    if store.exists(key):
        log.info("%s: %s already present, skipping", source_id, key)
        return key
    own_client = client is None
    client = client or make_client()
    features: list[Any] = []
    header: dict[str, Any] = {}
    offset = 0
    try:
        while True:
            params: dict[str, Any] = {
                "where": where,
                "outFields": out_fields,
                "returnGeometry": "true" if geometry else "false",
                "outSR": out_sr,
                "resultOffset": offset,
                "resultRecordCount": page_size,
                "f": "json",
            }
            payload = get_json(client, url, params)
            page = payload.get("features", [])
            features.extend(page)
            if not header:
                header = {k: v for k, v in payload.items() if k != "features"}
            more = payload.get("exceededTransferLimit") or (
                payload.get("properties", {}).get("exceededTransferLimit")
            )
            if not page or not more:
                break
            offset += len(page)
            log.info("%s: %d features so far", source_id, len(features))
    finally:
        if own_client:
            client.close()
    header.pop("exceededTransferLimit", None)
    document = {**header, "query": {"url": url, "where": where}, "features": features}
    put_json(store, key, document, url=f"{url}?where={where}")
    log.info("%s: stored %s (%d features)", source_id, key, len(features))
    return key
