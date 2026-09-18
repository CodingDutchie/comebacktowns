"""Write the scope to the towns table and drop rows that fell out of scope."""

from __future__ import annotations

import logging

from pipeline.load.d1 import D1Client
from pipeline.scope import TOWN_COLUMNS, Town

log = logging.getLogger(__name__)


def load_towns(towns: list[Town], d1: D1Client) -> tuple[int, int]:
    existing = {row["geoid"] for row in d1.query("SELECT geoid FROM towns")}
    current = {t.geoid for t in towns}
    stale = sorted(existing - current)
    written = d1.upsert("towns", TOWN_COLUMNS, [t.row() for t in towns], conflict=["geoid"])
    removed = d1.delete_where_in("towns", "geoid", stale) if stale else 0
    if removed:
        log.info("towns: removed %d rows no longer in scope", removed)
    return written, removed
