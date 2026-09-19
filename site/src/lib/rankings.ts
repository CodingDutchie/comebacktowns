import { metric, momentum, momentumLabels, scores, towns, usable, type Town } from "./data";
import { formatValue, score1 } from "./format";

export interface RankingRow {
  town: Town;
  readiness: number | null;
  grade: string | null;
  primary: number;
  primaryLabel: string;
  extra: string;
}

export interface Ranking {
  slug: string;
  title: string;
  description: string;
  /** One sentence for the home page cards. */
  question: string;
  primaryLabel: string;
  /** How the primary figure is printed. */
  fmt: (v: number) => string;
  rows: () => RankingRow[];
}

function scored(): Town[] {
  return towns.filter((t) => scores[t.geoid]);
}

function withinHour(t: Town): boolean {
  const hub = metric(t.geoid, "drive_min_regional_hub");
  const nyc = metric(t.geoid, "drive_min_nyc");
  return (usable(hub) && hub.value <= 60) || (usable(nyc) && nyc.value <= 60);
}

function priceRatio(t: Town): number | null {
  const home = metric(t.geoid, "median_home_value");
  const metro = metric(t.geoid, "metro_median_home_value");
  return usable(home) && usable(metro) && metro.value > 0 ? home.value / metro.value : null;
}

export const rankings: Ranking[] = [
  {
    slug: "highest-readiness",
    title: "Highest readiness",
    question: "Every town by readiness, with grades curved within population band.",
    description: "Every scored town by readiness. Grades are curved within population band, so a B in a village and a B in a city mean the same rank, not the same number.",
    primaryLabel: "Readiness",
    fmt: score1,
    rows: () =>
      scored()
        .map((town) => ({ town, s: scores[town.geoid] }))
        .sort((a, b) => b.s.readiness - a.s.readiness)
        .map(({ town, s }) => ({ town, readiness: s.readiness, grade: s.grade, primary: s.readiness, primaryLabel: "Readiness", extra: `${Math.round(s.coverage * 100)}% coverage` })),
  },
  {
    slug: "strongest-momentum",
    title: "Strongest momentum",
    question: "Where something is happening now, whatever the grade.",
    description: "Every town with a momentum label, by momentum score: home values and population against the typical New York place, county tax-filer migration against the typical New York county, and the change in the town's own permit rate. 50 is keeping pace; 60 and above is rising, below 40 is fading.",
    primaryLabel: "Momentum",
    fmt: score1,
    rows: () =>
      towns
        .filter((t) => momentum[t.geoid]?.label)
        .map((town) => ({ town, s: scores[town.geoid], m: momentum[town.geoid] }))
        .sort((a, b) => b.m.momentum - a.m.momentum)
        .map(({ town, s, m }) => ({
          town,
          readiness: s?.readiness ?? null,
          grade: s?.grade ?? null,
          primary: m.momentum,
          primaryLabel: "Momentum",
          extra: `${momentumLabels[m.label!] ?? m.label} · ${Math.round(m.coverage * 100)}% coverage`,
        })),
  },
  {
    slug: "price-headroom",
    title: "Best price headroom",
    question: "Priced near 60% of the metro median: room to rise, not yet found.",
    description: "Towns whose home prices sit near 60% of their metro median: cheap enough to have room, not so cheap that nobody is buying. Ranked by the price-headroom factor, then readiness.",
    primaryLabel: "Price ratio to metro",
    fmt: (v) => `${(v * 100).toFixed(0)}%`,
    rows: () =>
      scored()
        .map((town) => ({ town, s: scores[town.geoid], ratio: priceRatio(town), f: scores[town.geoid].factor_scores.price_headroom }))
        .filter((r) => r.f !== null && r.ratio !== null)
        .sort((a, b) => (b.f! - a.f!) || b.s.readiness - a.s.readiness)
        .map(({ town, s, ratio, f }) => ({ town, readiness: s.readiness, grade: s.grade, primary: ratio!, primaryLabel: "Price ratio to metro", extra: `factor ${f!.toFixed(2)}` })),
  },
  {
    slug: "value-within-an-hour",
    title: "Best value within an hour of a city",
    question: "Under 60 minutes to New York City or a regional hub, by price headroom.",
    description: "Towns within a 60-minute drive of New York City or a regional hub, ranked by price headroom and then readiness.",
    primaryLabel: "Minutes to nearest hub",
    fmt: (v) => (Number.isNaN(v) ? "n/a" : `${Math.round(v)} min`),
    rows: () =>
      scored()
        .filter(withinHour)
        .map((town) => ({ town, s: scores[town.geoid], f: scores[town.geoid].factor_scores.price_headroom ?? -1, hub: metric(town.geoid, "drive_min_regional_hub") }))
        .sort((a, b) => (b.f - a.f) || b.s.readiness - a.s.readiness)
        .map(({ town, s, f, hub }) => ({ town, readiness: s.readiness, grade: s.grade, primary: usable(hub) ? hub.value : NaN, primaryLabel: "Minutes to nearest hub", extra: f >= 0 ? `headroom ${f.toFixed(2)}` : "no price data" })),
  },
  {
    slug: "most-affordable",
    title: "Most affordable towns",
    question: "The lowest median home values in scope, with the metro median beside each.",
    description: "Every scored town by median home value (ACS 5-year), lowest first, with its price as a share of the metro median. Cheap is not the same as ready: the grade beside each row says whether the ingredients are there.",
    primaryLabel: "Median home value",
    fmt: (v) => formatValue("median_home_value", v),
    rows: () =>
      scored()
        .map((town) => ({ town, s: scores[town.geoid], home: metric(town.geoid, "median_home_value"), ratio: priceRatio(town) }))
        .filter((r) => usable(r.home))
        .sort((a, b) => a.home!.value! - b.home!.value!)
        .map(({ town, s, home, ratio }) => ({ town, readiness: s.readiness, grade: s.grade, primary: home!.value!, primaryLabel: "Median home value", extra: ratio !== null ? `${Math.round(ratio * 100)}% of metro median` : "no metro figure" })),
  },
  {
    slug: "near-a-train",
    title: "Towns near a train to New York City",
    question: "Within two miles of an Amtrak or Metro-North station, nearest to the city first.",
    description: "Scored towns within two miles (straight line) of an Amtrak or Metro-North station, ordered by drive time to New York City. Rail distance is from the station list; the drive is a road route, not a timetable.",
    primaryLabel: "Drive to NYC",
    fmt: (v) => formatValue("drive_min_nyc", v),
    rows: () =>
      scored()
        .map((town) => ({ town, s: scores[town.geoid], rail: metric(town.geoid, "miles_to_rail_station"), nyc: metric(town.geoid, "drive_min_nyc") }))
        .filter((r) => usable(r.rail) && r.rail.value <= 2 && usable(r.nyc))
        .sort((a, b) => a.nyc!.value! - b.nyc!.value!)
        .map(({ town, s, rail, nyc }) => ({ town, readiness: s.readiness, grade: s.grade, primary: nyc!.value!, primaryLabel: "Drive to NYC", extra: `${formatValue("miles_to_rail_station", rail!.value)} to a station` })),
  },
  {
    slug: "state-backed-downtowns",
    title: "Downtown Revitalization Initiative and NY Forward winners",
    question: "Every town in scope that has won a state downtown award, largest latest award first.",
    description: "Towns that have won at least one Downtown Revitalization Initiative or NY Forward award, ordered by the latest award amount and then readiness. Civic capacity is one of the six readiness factors; the award is the state's bet, the grade is ours.",
    primaryLabel: "Latest award",
    fmt: (v) => formatValue("dri_award_amount", v),
    rows: () =>
      scored()
        .map((town) => ({ town, s: scores[town.geoid], count: metric(town.geoid, "dri_award_count"), amount: metric(town.geoid, "dri_award_amount") }))
        .filter((r) => usable(r.count) && r.count.value >= 1)
        .sort((a, b) => ((usable(b.amount) ? b.amount.value : 0) - (usable(a.amount) ? a.amount.value : 0)) || b.s.readiness - a.s.readiness)
        .map(({ town, s, count, amount }) => ({ town, readiness: s.readiness, grade: s.grade, primary: usable(amount) ? amount.value : 0, primaryLabel: "Latest award", extra: `${count!.value} award${count!.value === 1 ? "" : "s"}` })),
  },
];

export const rankingBySlug = new Map(rankings.map((r) => [r.slug, r]));
