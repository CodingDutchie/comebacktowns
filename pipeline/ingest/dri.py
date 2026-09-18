"""DRI and NY Forward award pages from ny.gov: the program page plus every round page.

This is a scrape, so the HTML is snapshotted as-is; ``pipeline.transform.dri`` parses it.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import urljoin

import httpx

from pipeline.http import get, make_client
from pipeline.ingest.base import normalise_as_of, put_json, source
from pipeline.storage import RawStore, raw_key, raw_store, write_meta

log = logging.getLogger(__name__)

SOURCE_ID = "dri"


def discover_round_links(html: str, pattern: str, base_url: str) -> list[str]:
    seen: list[str] = []
    for match in re.finditer(pattern, html):
        url = urljoin(base_url, match.group(1))
        if url not in seen:
            seen.append(url)
    return seen


def round_slug(url: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", url.rstrip("/").rsplit("/", 1)[-1].lower()).strip("-")


def _store_html(store: RawStore, key: str, url: str, html: str) -> None:
    import hashlib

    data = html.encode()
    store.put_bytes(key, data, "text/html")
    write_meta(
        store,
        key,
        url=url,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        content_type="text/html",
    )


def fetch(
    as_of: str | date | None = None,
    *,
    store: RawStore | None = None,
    client: httpx.Client | None = None,
) -> list[str]:
    entry = source(SOURCE_ID)
    as_of_str = normalise_as_of(as_of)
    store = store or raw_store()
    own_client = client is None
    client = client or make_client()
    keys: list[str] = []
    manifest: dict[str, list[dict[str, str]]] = {}
    try:
        for program, page_url in entry["pages"].items():
            program_key = raw_key(SOURCE_ID, as_of_str, f"{program}_program.html")
            if store.exists(program_key):
                html = store.get_bytes(program_key).decode()
                log.info("%s: %s already present, skipping", SOURCE_ID, program_key)
            else:
                html = get(client, page_url).text
                _store_html(store, program_key, page_url, html)
            keys.append(program_key)
            pages = [{"url": page_url, "key": program_key, "kind": "program"}]
            round_urls = discover_round_links(html, entry["round_link_pattern"], page_url)
            if not round_urls:
                raise RuntimeError(f"{SOURCE_ID}: no round links found on {page_url}")
            for url in round_urls:
                key = raw_key(SOURCE_ID, as_of_str, f"{program}_{round_slug(url)}.html")
                if store.exists(key):
                    log.info("%s: %s already present, skipping", SOURCE_ID, key)
                else:
                    _store_html(store, key, url, get(client, url).text)
                keys.append(key)
                pages.append({"url": url, "key": key, "kind": "round"})
            manifest[program] = pages
    finally:
        if own_client:
            client.close()
    manifest_key = raw_key(SOURCE_ID, as_of_str, "manifest.json")
    put_json(store, manifest_key, manifest, url=", ".join(entry["pages"].values()))
    keys.append(manifest_key)
    return keys
