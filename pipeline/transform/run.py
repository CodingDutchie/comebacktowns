"""Run every transform for one snapshot date and return the rows."""

from __future__ import annotations

import logging
from collections.abc import Callable

from pipeline.scope import Town, towns_from_store
from pipeline.storage import RawStore
from pipeline.transform import Context, MetricRow
from pipeline.transform.acs import acs_metrics
from pipeline.transform.dri import dri_metrics
from pipeline.transform.irs import irs_metrics
from pipeline.transform.nrhp import nrhp_metrics
from pipeline.transform.osm import osm_metrics
from pipeline.transform.osrm import crow_metrics, osrm_metrics
from pipeline.transform.permits import permits_metrics
from pipeline.transform.popest import popest_metrics
from pipeline.transform.rail import rail_metrics
from pipeline.transform.zillow import zillow_metrics

log = logging.getLogger(__name__)

TRANSFORMS: dict[str, Callable[[Context], list[MetricRow]]] = {
    "popest": popest_metrics,
    "acs": acs_metrics,
    "permits": permits_metrics,
    "zillow": zillow_metrics,
    "nrhp": nrhp_metrics,
    "rail": rail_metrics,
    "osm": osm_metrics,
    "osrm": osrm_metrics,
    "crow": crow_metrics,
    "dri": dri_metrics,
    "irs": irs_metrics,
}


def run_transforms(
    store: RawStore,
    as_of: str,
    *,
    towns: list[Town] | None = None,
    only: list[str] | None = None,
) -> list[MetricRow]:
    ctx = Context(store=store, as_of=as_of, towns=towns or towns_from_store(store, as_of))
    rows: list[MetricRow] = []
    for name, transform in TRANSFORMS.items():
        if only and name not in only:
            continue
        produced = transform(ctx)
        log.info("transform %s: %d rows", name, len(produced))
        rows.extend(produced)
    return rows
