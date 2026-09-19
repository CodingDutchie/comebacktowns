"""Outbound HTTP: one client, a descriptive User-Agent, retries with backoff, streaming.

Every request identifies the project and its contact address so a publisher can reach us.
URLs are redacted before they are logged.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Iterator
from typing import IO, Any

import httpx

from pipeline.settings import redact_url, site_config

log = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=20.0)
CHUNK_BYTES = 1 << 20


def user_agent() -> str:
    site = site_config()
    return f"{site['SITE_NAME']}/0.1 (+https://{site['SITE_DOMAIN']}; {site['CONTACT_EMAIL']})"


def make_client(timeout: httpx.Timeout = DEFAULT_TIMEOUT, **kwargs: Any) -> httpx.Client:
    headers = {"User-Agent": user_agent(), **kwargs.pop("headers", {})}
    # Bind to an IPv4 local address so dual-stack hosts (Overpass among them) are never
    # reached over IPv6 from a runner without an IPv6 route ("Network is unreachable").
    # (S104 is about listening sockets; this is the source address of outbound connections.)
    transport = kwargs.pop("transport", None) or httpx.HTTPTransport(local_address="0.0.0.0")  # noqa: S104
    return httpx.Client(
        headers=headers, timeout=timeout, follow_redirects=True, transport=transport, **kwargs
    )


def _retry_after(response: httpx.Response | None, attempt: int, base: float) -> float:
    if response is not None:
        header = response.headers.get("Retry-After")
        if header and header.isdigit():
            return float(header)
    return base * (2**attempt)


def with_retry(
    call: Callable[[], httpx.Response],
    *,
    retries: int = 5,
    backoff: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    describe: str = "request",
) -> httpx.Response:
    """Run ``call`` until it returns a non-retryable response, with exponential backoff."""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        response: httpx.Response | None = None
        try:
            response = call()
        except httpx.TransportError as exc:
            last_error = exc
            log.warning("%s: transport error %s (attempt %d)", describe, exc, attempt + 1)
        else:
            if response.status_code not in RETRY_STATUSES:
                return response
            last_error = httpx.HTTPStatusError(
                f"{response.status_code} from {describe}",
                request=response.request,
                response=response,
            )
            log.warning("%s: HTTP %d (attempt %d)", describe, response.status_code, attempt + 1)
        if attempt < retries:
            sleep(_retry_after(response, attempt, backoff))
    assert last_error is not None
    raise last_error


def get(client: httpx.Client, url: str, **kwargs: Any) -> httpx.Response:
    """GET with retries; raises for any final non-2xx status."""
    response = with_retry(lambda: client.get(url, **kwargs), describe=redact_url(url))
    response.raise_for_status()
    return response


ABSENT_STATUSES = frozenset({403, 404, 410})


def exists(client: httpx.Client, url: str, **kwargs: Any) -> bool:
    """Whether ``url`` is published: HEAD (falling back to a GET that reads no body when a
    server refuses HEAD), retried like any request. A 404-class status means "not yet";
    anything else that is not 2xx raises, so an outage never looks like an unreleased file.
    """
    describe = redact_url(url)
    response = with_retry(lambda: client.head(url, **kwargs), describe=describe)
    if response.status_code == 405:

        def probe() -> httpx.Response:
            with client.stream("GET", url, **kwargs) as streamed:
                return streamed

        response = with_retry(probe, describe=describe)
    if response.status_code in ABSENT_STATUSES:
        return False
    response.raise_for_status()
    return True


class HashingReader:
    """A read()-able wrapper over a byte iterator that hashes and counts what passes through.

    boto3's ``upload_fileobj`` reads from this in multipart chunks, so a response body flows
    from the publisher to R2 without touching local disk or being held whole in memory.
    """

    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = chunks
        self._buffer = b""
        self.sha256 = hashlib.sha256()
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            parts = [self._buffer, *self._chunks]
            self._buffer = b""
            out = b"".join(parts)
        else:
            while len(self._buffer) < size:
                try:
                    self._buffer += next(self._chunks)
                except StopIteration:
                    break
            out, self._buffer = self._buffer[:size], self._buffer[size:]
        self.sha256.update(out)
        self.bytes_read += len(out)
        return out


def stream_get(
    client: httpx.Client,
    url: str,
    sink: Callable[[HashingReader, str | None], None],
    *,
    retries: int = 5,
    backoff: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[int, str]:
    """Stream a GET body into ``sink(reader, content_type)``; returns (bytes, sha256 hex).

    The whole transfer is retried on a retryable status or a transport error, since a
    partial upload is not resumable in a useful way.
    """
    describe = redact_url(url)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with client.stream("GET", url) as response:
                if response.status_code in RETRY_STATUSES:
                    log.warning(
                        "%s: HTTP %d (attempt %d)", describe, response.status_code, attempt + 1
                    )
                    last_error = httpx.HTTPStatusError(
                        f"{response.status_code} from {describe}",
                        request=response.request,
                        response=response,
                    )
                    sleep(_retry_after(response, attempt, backoff))
                    continue
                response.raise_for_status()
                reader = HashingReader(response.iter_bytes(CHUNK_BYTES))
                sink(reader, response.headers.get("Content-Type"))
                return reader.bytes_read, reader.sha256.hexdigest()
        except httpx.TransportError as exc:
            last_error = exc
            log.warning("%s: transport error %s (attempt %d)", describe, exc, attempt + 1)
            sleep(_retry_after(None, attempt, backoff))
    assert last_error is not None
    raise last_error


def copy_stream(reader: HashingReader, out: IO[bytes]) -> None:
    while chunk := reader.read(CHUNK_BYTES):
        out.write(chunk)
