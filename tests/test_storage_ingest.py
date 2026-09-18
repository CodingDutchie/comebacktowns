import httpx

from pipeline.ingest.base import fetch_url_to_store
from pipeline.storage import LocalStore, raw_key, read_meta


def test_raw_key_layout():
    assert (
        raw_key("popest", "2026-09-18", "sub-est2024.csv")
        == "raw/popest/2026-09-18/sub-est2024.csv"
    )


def test_local_store_roundtrip(local_store: LocalStore):
    local_store.put_bytes("raw/a/2026-01-01/x.txt", b"hello")
    assert local_store.exists("raw/a/2026-01-01/x.txt")
    assert not local_store.exists("raw/a/2026-01-01/y.txt")
    assert local_store.get_bytes("raw/a/2026-01-01/x.txt") == b"hello"
    assert local_store.list("raw/a") == ["raw/a/2026-01-01/x.txt"]


def test_fetch_is_streamed_and_idempotent(local_store: LocalStore):
    hits = []

    def handler(request):
        hits.append(1)
        return httpx.Response(200, content=b"csv,data\n1,2\n", headers={"Content-Type": "text/csv"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    key = fetch_url_to_store(
        "popest", "https://x/f.csv", "f.csv", "2026-09-18", store=local_store, client=client
    )
    assert key == "raw/popest/2026-09-18/f.csv"
    assert local_store.get_bytes(key) == b"csv,data\n1,2\n"
    meta = read_meta(local_store, key)
    assert (
        meta["url"] == "https://x/f.csv"
        and meta["bytes"] == 13
        and meta["content_type"] == "text/csv"
    )
    again = fetch_url_to_store(
        "popest", "https://x/f.csv", "f.csv", "2026-09-18", store=local_store, client=client
    )
    assert again == key and len(hits) == 1, "second fetch must be a no-op"
