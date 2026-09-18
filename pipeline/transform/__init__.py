"""Raw snapshots -> tidy metric rows. Every row names its source file and as-of date."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from pipeline.scope import Town
from pipeline.storage import RawStore

METRIC_COLUMNS = [
    "geoid",
    "metric",
    "period",
    "value",
    "moe",
    "suppressed",
    "source_id",
    "as_of",
    "r2_key",
]


class MetricRow(BaseModel):
    geoid: str = Field(pattern=r"^\d{7}$")
    metric: str
    period: str
    value: float | None
    moe: float | None = None
    suppressed: int = 0
    source_id: str
    as_of: str
    r2_key: str = Field(pattern=r"^raw/.+")

    def row(self) -> list[Any]:
        return [getattr(self, c) for c in METRIC_COLUMNS]


@dataclass
class Context:
    """What every transform needs: the store, the snapshot date and the scope."""

    store: RawStore
    as_of: str
    towns: list[Town]
    _keys: dict[str, list[str]] = field(default_factory=dict)

    @property
    def by_geoid(self) -> dict[str, Town]:
        return {t.geoid: t for t in self.towns}

    def keys(self, source_id: str) -> list[str]:
        """Raw keys for a source at this as-of, excluding sidecars. Never fetches."""
        if source_id not in self._keys:
            prefix = f"raw/{source_id}/{self.as_of}/"
            keys = [k for k in self.store.list(prefix) if not k.endswith(".meta.json")]
            if not keys:
                raise FileNotFoundError(
                    f"no raw files under {prefix}; run `pipeline.cli ingest {source_id}` first"
                )
            self._keys[source_id] = sorted(keys)
        return self._keys[source_id]

    def key(self, source_id: str, filename: str) -> str:
        key = f"raw/{source_id}/{self.as_of}/{filename}"
        if key not in self.keys(source_id):
            raise FileNotFoundError(f"{key} is not in the store")
        return key

    def population(self, geoid: str) -> int | None:
        return self.by_geoid[geoid].pop_latest


def suppress_if_wide(value: float | None, moe: float | None, threshold: float = 0.4) -> int:
    """QA rule 1: an ACS value whose MOE exceeds 40% of the estimate is suppressed."""
    if value is None or moe is None:
        return 0
    if value == 0:
        return 1 if moe > 0 else 0
    return 1 if moe > threshold * abs(value) else 0
