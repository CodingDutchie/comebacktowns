"""Build the in-scope town list from the popest sub-county file and the Gazetteer.

popest supplies name, legal type, population and county (via the county-part rows);
the Gazetteer supplies coordinates. Both are keyed on the 7-digit place GEOID.
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
import zipfile
from collections import defaultdict
from typing import Any

import polars as pl
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

SUMLEV_PLACE = "162"
SUMLEV_PLACE_COUNTY_PART = "157"
LEGAL_SUFFIXES = ("city", "village", "town", "CDP", "borough")


class Town(BaseModel):
    geoid: str = Field(pattern=r"^\d{7}$")
    name: str
    legal_type: str
    county: str
    county_fips: str = Field(pattern=r"^\d{3}$")
    region: str
    lat: float
    lon: float
    pop_latest: int | None
    pop_latest_year: int | None
    slug: str

    def row(self) -> list[Any]:
        return [
            self.geoid,
            self.name,
            self.legal_type,
            self.county,
            self.county_fips,
            self.region,
            self.lat,
            self.lon,
            self.pop_latest,
            self.pop_latest_year,
            self.slug,
        ]


TOWN_COLUMNS = [
    "geoid",
    "name",
    "legal_type",
    "county",
    "county_fips",
    "region",
    "lat",
    "lon",
    "pop_latest",
    "pop_latest_year",
    "slug",
]


def split_legal_name(census_name: str) -> tuple[str, str]:
    """``"Catskill village"`` -> ``("Catskill", "village")``."""
    for suffix in LEGAL_SUFFIXES:
        if census_name.endswith(" " + suffix):
            return census_name[: -len(suffix) - 1], suffix.lower()
    return census_name, "unknown"


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def county_lookup(scope: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """county_fips -> (county name, region)."""
    out: dict[str, tuple[str, str]] = {}
    for region, counties in scope["regions"].items():
        for fips, name in counties.items():
            fips = str(fips).zfill(3)
            if fips in out:
                raise ValueError(f"county {fips} appears in two regions")
            out[fips] = (str(name), str(region))
    return out


def read_popest(data: bytes) -> pl.DataFrame:
    return pl.read_csv(io.BytesIO(data), infer_schema_length=0, encoding="utf8-lossy")


def read_gazetteer(data: bytes) -> pl.DataFrame:
    """Accepts the zip as published or the extracted tab-separated text."""
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".txt")]
            if len(names) != 1:
                raise ValueError(f"expected one .txt in gazetteer zip, found {names}")
            data = zf.read(names[0])
    frame = pl.read_csv(
        io.BytesIO(data), separator="\t", infer_schema_length=0, encoding="utf8-lossy"
    )
    frame = frame.rename({c: c.strip() for c in frame.columns})
    return frame.with_columns(pl.col(pl.Utf8).str.strip_chars())


def latest_pop_column(columns: list[str]) -> tuple[str, int]:
    years = [(int(c[-4:]), c) for c in columns if re.fullmatch(r"POPESTIMATE\d{4}", c)]
    if not years:
        raise ValueError("no POPESTIMATE columns in popest file")
    year, column = max(years)
    return column, year


def build_towns(popest_bytes: bytes, gazetteer_bytes: bytes, scope: dict[str, Any]) -> list[Town]:
    state = str(scope["state_fips"]).zfill(2)
    legal_types = {str(t).lower() for t in scope["legal_types"]}
    pop_min, pop_max = int(scope["population"]["min"]), int(scope["population"]["max"])
    counties = county_lookup(scope)

    pop = read_popest(popest_bytes).filter(pl.col("STATE") == state)
    pop_col, pop_year = latest_pop_column(pop.columns)
    pop = pop.with_columns(pl.col(pop_col).cast(pl.Int64).alias("_pop"))

    # Primary county = the county holding the largest share of the place's population.
    parts = pop.filter(pl.col("SUMLEV") == SUMLEV_PLACE_COUNTY_PART)
    primary_part: dict[str, tuple[str, int]] = {}
    for place, county, part_pop in parts.select("PLACE", "COUNTY", "_pop").iter_rows():
        best = primary_part.get(place)
        if best is None or (part_pop or 0) > best[1]:
            primary_part[place] = (county, part_pop or 0)
    county_of = {place: county for place, (county, _) in primary_part.items()}

    gaz = read_gazetteer(gazetteer_bytes).filter(pl.col("GEOID").str.starts_with(state))
    coords = {
        geoid: (float(lat), float(lon))
        for geoid, lat, lon in gaz.select("GEOID", "INTPTLAT", "INTPTLONG").iter_rows()
    }

    whole = pop.filter(pl.col("SUMLEV") == SUMLEV_PLACE)
    towns: list[Town] = []
    skipped_no_coords: list[str] = []
    for place, name, funcstat, population in whole.select(
        "PLACE", "NAME", "FUNCSTAT", "_pop"
    ).iter_rows():
        base_name, legal_type = split_legal_name(name)
        if legal_type not in legal_types or funcstat != "A":
            continue
        if population is None or not (pop_min <= population <= pop_max):
            continue
        county_fips = county_of.get(place)
        if county_fips is None or county_fips not in counties:
            continue
        geoid = state + place
        if geoid not in coords:
            skipped_no_coords.append(f"{name} ({geoid})")
            continue
        county_name, region = counties[county_fips]
        lat, lon = coords[geoid]
        towns.append(
            Town(
                geoid=geoid,
                name=base_name,
                legal_type=legal_type,
                county=county_name,
                county_fips=county_fips,
                region=region,
                lat=lat,
                lon=lon,
                pop_latest=population,
                pop_latest_year=pop_year,
                slug="",
            )
        )
    if skipped_no_coords:
        raise ValueError(
            "places in scope with no Gazetteer coordinates (fix, do not skip): "
            + ", ".join(skipped_no_coords)
        )
    assign_slugs(towns)
    towns.sort(key=lambda t: t.geoid)
    log.info("scope: %d places in scope (population year %d)", len(towns), pop_year)
    return towns


def assign_slugs(towns: list[Town]) -> None:
    """``catskill-ny``; a name shared by two places gets the county added to both."""
    by_slug: dict[str, list[Town]] = defaultdict(list)
    for town in towns:
        by_slug[slugify(town.name)].append(town)
    for base, group in by_slug.items():
        if len(group) == 1:
            group[0].slug = f"{base}-ny"
            continue
        for town in group:
            town.slug = f"{base}-{slugify(town.county)}-ny"
    seen = defaultdict(list)
    for town in towns:
        seen[town.slug].append(town)
    dupes = {s: [t.geoid for t in g] for s, g in seen.items() if len(g) > 1}
    if dupes:
        raise ValueError(f"slug collision after county disambiguation: {dupes}")
