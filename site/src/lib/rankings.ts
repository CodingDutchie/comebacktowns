import { metric, momentum, momentumLabels, scores, towns, usable, type Town } from "./data";

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
    rows: () =>
      scored()
        .filter(withinHour)
        .map((town) => ({ town, s: scores[town.geoid], f: scores[town.geoid].factor_scores.price_headroom ?? -1, hub: metric(town.geoid, "drive_min_regional_hub") }))
        .sort((a, b) => (b.f - a.f) || b.s.readiness - a.s.readiness)
        .map(({ town, s, f, hub }) => ({ town, readiness: s.readiness, grade: s.grade, primary: usable(hub) ? hub.value : NaN, primaryLabel: "Minutes to nearest hub", extra: f >= 0 ? `headroom ${f.toFixed(2)}` : "no price data" })),
  },
];

export const rankingBySlug = new Map(rankings.map((r) => [r.slug, r]));
