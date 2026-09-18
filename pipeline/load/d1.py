"""D1 writer over the Cloudflare HTTP API: batched, parameterised, idempotent upserts.

D1 caps bound parameters per statement at 100, so multi-row inserts are chunked to fit.
Each request is one statement; reruns are safe because every write is an upsert keyed on
the table's primary key.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import httpx

from pipeline.http import with_retry
from pipeline.settings import d1_database_id, require_env

log = logging.getLogger(__name__)

MAX_PARAMS = 100
API = "https://api.cloudflare.com/client/v4"


class D1Error(RuntimeError):
    pass


class D1Client:
    def __init__(
        self,
        account_id: str,
        database_id: str,
        token: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.url = f"{API}/accounts/{account_id}/d1/database/{database_id}/query"
        self._client = client or httpx.Client(timeout=httpx.Timeout(120.0, connect=20.0))
        self._client.headers["Authorization"] = f"Bearer {token}"
        self._client.headers["Content-Type"] = "application/json"

    @classmethod
    def from_env(cls, *, client: httpx.Client | None = None) -> D1Client:
        return cls(
            require_env("CLOUDFLARE_ACCOUNT_ID"),
            d1_database_id(),
            require_env("CLOUDFLARE_API_TOKEN"),
            client=client,
        )

    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"sql": sql}
        if params is not None:
            body["params"] = list(params)
        response = with_retry(lambda: self._client.post(self.url, json=body), describe="d1 query")
        payload = response.json() if response.content else {}
        if response.status_code >= 400 or not payload.get("success"):
            errors = payload.get("errors") or [{"message": response.text[:500]}]
            # never echo params: they may be large and are never secrets, but the sql is enough
            raise D1Error(f"D1 {response.status_code}: {errors}; sql={sql[:200]!r}")
        results: list[dict[str, Any]] = []
        for statement in payload.get("result", []):
            results.extend(statement.get("results") or [])
        return results

    def upsert(
        self,
        table: str,
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
        conflict: Sequence[str],
    ) -> int:
        """INSERT ... ON CONFLICT DO UPDATE in batches that respect the parameter limit."""
        if not rows:
            return 0
        per_batch = max(1, MAX_PARAMS // len(columns))
        update_cols = [c for c in columns if c not in conflict]
        set_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols) or None
        conflict_clause = (
            f"ON CONFLICT({', '.join(conflict)}) DO UPDATE SET {set_clause}"
            if set_clause
            else f"ON CONFLICT({', '.join(conflict)}) DO NOTHING"
        )
        placeholder = "(" + ", ".join("?" for _ in columns) + ")"
        written = 0
        for start in range(0, len(rows), per_batch):
            chunk = rows[start : start + per_batch]
            # Identifiers come from code, never from data; values are bound parameters.
            values = ", ".join(placeholder for _ in chunk)
            sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES {values} {conflict_clause}"  # noqa: S608
            params = [v for row in chunk for v in row]
            self.query(sql, params)
            written += len(chunk)
        log.info("d1: upserted %d rows into %s", written, table)
        return written

    def delete_where_in(self, table: str, column: str, values: Sequence[Any]) -> int:
        deleted = 0
        for start in range(0, len(values), MAX_PARAMS):
            chunk = values[start : start + MAX_PARAMS]
            marks = ", ".join("?" for _ in chunk)
            self.query(f"DELETE FROM {table} WHERE {column} IN ({marks})", list(chunk))  # noqa: S608
            deleted += len(chunk)
        return deleted

    def count(self, table: str) -> int:
        rows = self.query(f"SELECT count(*) AS n FROM {table}")  # noqa: S608
        return int(rows[0]["n"])
