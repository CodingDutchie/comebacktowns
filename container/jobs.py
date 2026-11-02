"""The whitelist of jobs the refresh container will run, and the argv for each.

The orchestrator Worker names a job and gives parameters; nothing it sends is ever run as a
shell string. Parameters are validated here (the Worker validates too: defence in depth).
"""

from __future__ import annotations

import re
import sys
from typing import Any

PY = [sys.executable, "-m", "pipeline.cli"]
SOURCE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
DISCOVERABLE = ("permits", "irs")


def _pilot(params: dict[str, Any]) -> list[str]:
    skip = params.get("skip_pilot", False)
    if not isinstance(skip, bool):
        raise ValueError("skip_pilot must be a boolean")
    return ["--no-pilot"] if skip else []


def commands_for(job: str, params: dict[str, Any]) -> list[list[str]]:
    """Return the commands (run in order, stop at the first failure) for a named job."""
    if job == "ingest":
        source = params.get("source")
        if not isinstance(source, str) or not SOURCE.match(source):
            raise ValueError("ingest needs a source name like 'permits'")
        return [[*PY, "ingest", source]]
    if job == "osm_queries":
        return [[*PY, "osm-queries"]]
    if job == "discover":
        return [[*PY, "discover", *DISCOVERABLE]]
    if job == "validate":
        # All dry, one job: metrics.csv stays on disk for the score and momentum runs.
        return [
            [*PY, "transform", "--dry-run", "--out", "metrics.csv"],
            [*PY, "score", "--dry-run", "--metrics-csv", "metrics.csv", *_pilot(params)],
            [*PY, "momentum", "--dry-run", "--metrics-csv", "metrics.csv"],
        ]
    if job == "load":
        return [[*PY, "transform"], [*PY, "score", *_pilot(params)], [*PY, "momentum"]]
    if job == "publish":
        return [["bash", "container/publish.sh"]]
    raise ValueError(f"unknown job: {job!r}")
