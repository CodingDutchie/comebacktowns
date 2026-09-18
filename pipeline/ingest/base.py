"""Shared fetch logic: idempotent, streaming, dated keys."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

import httpx

from pipeline.http import HashingReader, make_client, stream_get
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
