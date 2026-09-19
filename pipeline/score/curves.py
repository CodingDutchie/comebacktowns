"""Named normalisation curves, 0-1, one per scoring input.

Every curve can explain itself in a sentence; the methodology page is built from
``describe()``. Missing inputs never reach a curve: the engine excludes them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class Curve(Protocol):
    @property
    def name(self) -> str: ...
    def __call__(self, value: float, **context: float) -> float: ...
    def describe(self) -> str: ...


def clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass(frozen=True)
class Linear:
    """Straight line from ``zero_at`` (scores 0) to ``one_at`` (scores 1), flat beyond both.

    When ``zero_at`` is larger than ``one_at`` the curve descends: lower values are better.
    """

    name: str
    zero_at: float
    one_at: float
    unit: str = ""
    better: str = ""
    scale: float = 1.0  # display only: 100 shows a share as percentage points

    def __call__(self, value: float, **context: float) -> float:
        return clamp((value - self.zero_at) / (self.one_at - self.zero_at))

    def describe(self) -> str:
        direction = "lower is better" if self.zero_at > self.one_at else "higher is better"
        one, zero = self.one_at * self.scale, self.zero_at * self.scale
        return (
            f"{self.name}: {direction}; scores 1 at {one:g}{self.unit} or "
            f"{'less' if self.zero_at > self.one_at else 'more'}, falling in a straight line to 0 "
            f"at {zero:g}{self.unit}."
        )


@dataclass(frozen=True)
class Flag:
    """A yes/no input scores 1 or 0."""

    name: str
    yes: str

    def __call__(self, value: float, **context: float) -> float:
        return 1.0 if value >= 0.5 else 0.0

    def describe(self) -> str:
        return f"{self.name}: 1 when {self.yes}, otherwise 0."


@dataclass(frozen=True)
class Peak:
    """A triangle: 0 at ``low``, 1 at ``peak``, back to 0 at ``high``. Not monotonic."""

    name: str
    low: float
    peak: float
    high: float
    what: str

    def __call__(self, value: float, **context: float) -> float:
        if value <= self.low or value >= self.high:
            return 0.0
        if value <= self.peak:
            return (value - self.low) / (self.peak - self.low)
        return (self.high - value) / (self.high - self.peak)

    def describe(self) -> str:
        return (
            f"{self.name}: {self.what}; scores 1 at {self.peak:g}, and 0 at or below {self.low:g} "
            f"and at or above {self.high:g}, with straight lines between."
        )


@dataclass(frozen=True)
class Recency:
    """1 for anything within ``full_years`` of the scoring year, fading to ``floor`` at
    ``fade_years`` and staying there. Older news still counts for something."""

    name: str
    full_years: float
    fade_years: float
    floor: float

    def __call__(self, value: float, **context: float) -> float:
        age = context["scoring_year"] - value
        if age <= self.full_years:
            return 1.0
        if age >= self.fade_years:
            return self.floor
        span = self.fade_years - self.full_years
        return 1.0 - (1.0 - self.floor) * (age - self.full_years) / span

    def describe(self) -> str:
        return (
            f"{self.name}: 1 when the award is at most {self.full_years:g} years old, fading in a "
            f"straight line to {self.floor:g} at {self.fade_years:g} years and staying there."
        )


@dataclass(frozen=True)
class Ratio:
    """Applies an inner curve to ``value / context[denominator]``."""

    name: str
    denominator: str
    inner: Peak

    def __call__(self, value: float, **context: float) -> float:
        den = context.get(self.denominator)
        if den is None or den <= 0:
            raise ValueError(f"{self.name} needs {self.denominator}")
        return self.inner(value / den)

    def describe(self) -> str:
        return f"{self.name} divided by {self.denominator}. " + self.inner.describe()


@dataclass(frozen=True)
class Relative:
    """Applies an inner curve to ``value - context[benchmark]``: how far the town's own
    change sits above or below a benchmark change. Keeping pace scores the inner curve's
    midpoint."""

    name: str
    benchmark: str
    inner: Linear

    def __call__(self, value: float, **context: float) -> float:
        bench = context.get(self.benchmark)
        if bench is None:
            raise ValueError(f"{self.name} needs {self.benchmark}")
        return self.inner(value - bench)

    def describe(self) -> str:
        return f"{self.name} minus {self.benchmark}. " + self.inner.describe()


# One curve per input named in config/scoring.v1.yml. Inputs that only supply context to
# another input's curve (metro_median_home_value, the *_ny_median benchmarks) are listed in
# CONTEXT_ONLY.
CURVES_V1: dict[str, Curve] = {
    "drive_min_nyc": Linear("drive_min_nyc", zero_at=240, one_at=60, unit=" min"),
    "drive_min_regional_hub": Linear("drive_min_regional_hub", zero_at=90, one_at=15, unit=" min"),
    "miles_to_rail_station": Linear("miles_to_rail_station", zero_at=30, one_at=2, unit=" mi"),
    "pre1940_share": Linear("pre1940_share", zero_at=0.10, one_at=0.60),
    "has_nrhp_district": Flag(
        "has_nrhp_district", "a National Register historic district lies within the place"
    ),
    "osm_business_per_1k": Linear("osm_business_per_1k", zero_at=2, one_at=20, unit=" per 1,000"),
    "median_home_value": Ratio(
        "median_home_value",
        "metro_median_home_value",
        Peak(
            "price ratio to the metro median",
            low=0.25,
            peak=0.60,
            high=1.20,
            what=(
                "cheapest is not best: a town priced well below its metro has headroom, one "
                "priced far below it has no demand yet, and one at or above it has already "
                "been found"
            ),
        ),
    ),
    "broadband_subscription_share": Linear(
        "broadband_subscription_share", zero_at=0.50, one_at=0.90
    ),
    "under_18_share": Linear("under_18_share", zero_at=0.12, one_at=0.25),
    "hospital_within_20min": Flag(
        "hospital_within_20min", "a hospital is within a 20-minute drive"
    ),
    "dri_award_amount": Linear("dri_award_amount", zero_at=0, one_at=10_000_000, unit=" USD"),
    "dri_award_year": Recency("dri_award_year", full_years=3, fade_years=10, floor=0.3),
}
# One curve per input named in config/momentum.v1.yml. Every input is a change over time
# judged against a benchmark, so keeping pace scores 0.5 and 50 is the steady centre.
MOMENTUM_CURVES_V1: dict[str, Curve] = {
    "zhvi_change_1y": Relative(
        "zhvi_change_1y",
        "zhvi_change_1y_ny_median",
        Linear(
            "one-year home value change against the typical New York place",
            zero_at=-0.05,
            one_at=0.05,
            unit=" percentage points",
            scale=100,
        ),
    ),
    "permit_rate_change": Linear(
        "permit_rate_change", zero_at=-2, one_at=2, unit=" units per 1,000 residents a year"
    ),
    "population_change": Relative(
        "population_change",
        "population_change_ny_median",
        Linear(
            "population change since 2020 against the typical New York place",
            zero_at=-0.03,
            one_at=0.03,
            unit=" percentage points",
            scale=100,
        ),
    ),
}
CONTEXT_ONLY = {
    "metro_median_home_value",
    "zhvi_change_1y_ny_median",
    "zori_change_1y_ny_median",
    "population_change_ny_median",
}
CURVES: dict[str, dict[str, Curve]] = {"v1": CURVES_V1}
MOMENTUM_CURVES: dict[str, dict[str, Curve]] = {"v1": MOMENTUM_CURVES_V1}
