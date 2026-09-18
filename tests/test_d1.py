import json

import httpx
import pytest

from pipeline.load.d1 import D1Client, D1Error
from pipeline.load.towns import load_towns
from pipeline.scope import build_towns


def make_client(handler):
    transport = httpx.MockTransport(handler)
    return D1Client("acct", "dbid", "tok", client=httpx.Client(transport=transport))


def test_upsert_batches_within_param_limit():
    bodies = []

    def handler(request):
        assert request.headers["Authorization"] == "Bearer tok"
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"success": True, "result": [{"results": []}]})

    d1 = make_client(handler)
    cols = ["a", "b", "c"]  # 33 rows per statement
    rows = [[i, i, i] for i in range(70)]
    assert d1.upsert("t", cols, rows, conflict=["a"]) == 70
    assert [len(b["params"]) for b in bodies] == [99, 99, 12]
    assert bodies[0]["sql"].startswith("INSERT INTO t (a, b, c) VALUES (?, ?, ?), ")
    assert bodies[0]["sql"].endswith("ON CONFLICT(a) DO UPDATE SET b=excluded.b, c=excluded.c")


def test_query_raises_on_api_error():
    d1 = make_client(
        lambda r: httpx.Response(400, json={"success": False, "errors": [{"message": "nope"}]})
    )
    with pytest.raises(D1Error, match="nope"):
        d1.query("SELECT 1")


def test_load_towns_upserts_and_removes_stale(popest_bytes, gazetteer_zip, scope):
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if body["sql"].startswith("SELECT geoid"):
            results = [{"geoid": "3613002"}, {"geoid": "3600001"}]
        elif body["sql"].startswith("SELECT count"):
            results = [{"n": 4}]
        else:
            results = []
        return httpx.Response(200, json={"success": True, "result": [{"results": results}]})

    towns = build_towns(popest_bytes, gazetteer_zip, scope)
    written, removed = load_towns(towns, make_client(handler))
    assert written == 4 and removed == 1
    delete = [b for b in bodies if b["sql"].startswith("DELETE")]
    assert delete == [{"sql": "DELETE FROM towns WHERE geoid IN (?)", "params": ["3600001"]}]
