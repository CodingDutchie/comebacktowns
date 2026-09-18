import httpx
import pytest

from pipeline import http


def test_user_agent_names_contact():
    ua = http.user_agent()
    assert "data@comebacktowns.com" in ua and "comebacktowns.com" in ua


def test_with_retry_backs_off_then_succeeds():
    calls = []
    sleeps = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    response = http.with_retry(lambda: client.get("https://x/"), sleep=sleeps.append, backoff=1.0)
    assert response.text == "ok" and len(calls) == 3
    assert sleeps == [1.0, 2.0]


def test_with_retry_gives_up():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        http.with_retry(lambda: client.get("https://x/"), retries=2, sleep=lambda s: None)


def test_with_retry_honours_retry_after():
    n = {"i": 0}

    def handler(request):
        n["i"] += 1
        if n["i"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200)

    sleeps = []
    client = httpx.Client(transport=httpx.MockTransport(handler))
    http.with_retry(lambda: client.get("https://x/"), sleep=sleeps.append)
    assert sleeps == [7.0]


def test_stream_get_hashes_and_counts(tmp_path):
    body = b"a" * (3 * 1024 * 1024 + 17)
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))
    )
    out = tmp_path / "f"
    with out.open("wb") as fh:
        size, digest = http.stream_get(
            client, "https://x/f", lambda reader, ct: http.copy_stream(reader, fh)
        )
    import hashlib

    assert size == len(body) and digest == hashlib.sha256(body).hexdigest()
    assert out.read_bytes() == body


def test_stream_get_retries_whole_transfer():
    n = {"i": 0}

    def handler(request):
        n["i"] += 1
        return httpx.Response(502) if n["i"] == 1 else httpx.Response(200, content=b"data")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    got = []
    size, _ = http.stream_get(
        client, "https://x/", lambda r, ct: got.append(r.read()), sleep=lambda s: None
    )
    assert got == [b"data"] and size == 4


def test_make_client_pins_ipv4():
    client = http.make_client()
    pool = client._transport._pool  # type: ignore[attr-defined]
    assert pool._local_address == "0.0.0.0"
