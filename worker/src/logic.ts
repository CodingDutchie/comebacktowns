/**
 * Pure search / filter / compare over an in-memory town index. No I/O here, so it is unit
 * tested in Node; `index.ts` wires it to D1, KV and HTTP.
 */

export interface TownRow {
  geoid: string;
  name: string;
  legal_type: string;
  county: string;
  region: string;
  lat: number;
  lon: number;
  pop_latest: number | null;
  slug: string;
}

export interface ScoreRow {
  geoid: string;
  readiness: number;
  grade: string | null;
  coverage: number;
  factor_scores: string; // JSON
  computed_at: string;
}

export interface MetricRow {
  geoid: string;
  metric: string;
  period: string;
  value: number | null;
  suppressed: number;
}

export interface Fact {
  value: number | null;
  period: string;
  suppressed: boolean;
}

export interface IndexedTown {
  geoid: string;
  slug: string;
  name: string;
  legal_type: string;
  county: string;
  region: string;
  lat: number;
  lon: number;
  population: number | null;
  band: "under_5000" | "5000_plus";
  readiness: number | null;
  grade: string | null;
  coverage: number | null;
  factors: Record<string, number | null>;
  facts: Record<string, Fact>;
  search: string; // lower-cased haystack
}

export interface TownIndex {
  built_at: string;
  computed_at: string | null;
  towns: IndexedTown[];
}

export const FACT_METRICS = [
  "median_home_value",
  "median_gross_rent",
  "zhvi",
  "zori",
  "drive_min_nyc",
  "drive_min_regional_hub",
  "drive_min_nearest_hospital",
  "miles_to_rail_station",
  "osm_business_count",
  "osm_business_per_1k",
  "permits_per_1k",
  "pre1940_share",
  "under_18_share",
  "broadband_subscription_share",
  "vacancy_rate",
  "population_change",
  "dri_award_amount",
  "dri_award_year",
  "has_nrhp_district",
] as const;

export function buildIndex(
  towns: TownRow[],
  scores: ScoreRow[],
  metrics: MetricRow[],
  now: () => string = () => new Date().toISOString(),
): TownIndex {
  // latest scores run only
  const latestRun = scores.reduce<string | null>((m, s) => (m === null || s.computed_at > m ? s.computed_at : m), null);
  const scoreBy = new Map<string, ScoreRow>();
  for (const s of scores) if (s.computed_at === latestRun) scoreBy.set(s.geoid, s);
  // latest period per (geoid, metric)
  const facts = new Map<string, Record<string, Fact>>();
  for (const m of metrics) {
    const per = facts.get(m.geoid) ?? {};
    const cur = per[m.metric];
    if (!cur || m.period > cur.period) per[m.metric] = { value: m.value, period: m.period, suppressed: !!m.suppressed };
    facts.set(m.geoid, per);
  }
  const out: IndexedTown[] = towns.map((t) => {
    const s = scoreBy.get(t.geoid);
    return {
      geoid: t.geoid,
      slug: t.slug,
      name: t.name,
      legal_type: t.legal_type,
      county: t.county,
      region: t.region,
      lat: t.lat,
      lon: t.lon,
      population: t.pop_latest,
      band: (t.pop_latest ?? 0) < 5000 ? "under_5000" : "5000_plus",
      readiness: s ? s.readiness : null,
      grade: s ? s.grade : null,
      coverage: s ? s.coverage : null,
      factors: s ? (JSON.parse(s.factor_scores) as Record<string, number | null>) : {},
      facts: facts.get(t.geoid) ?? {},
      search: `${t.name} ${t.county} ${t.slug}`.toLowerCase(),
    };
  });
  out.sort((a, b) => a.name.localeCompare(b.name));
  return { built_at: now(), computed_at: latestRun, towns: out };
}

function fold(s: string): string {
  return s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}

export interface SearchHit {
  slug: string;
  name: string;
  legal_type: string;
  county: string;
  region: string;
  grade: string | null;
  readiness: number | null;
}

/** Prefix matches on the name rank first, then word-prefix, then substring. */
export function search(index: TownIndex, q: string, limit = 10): SearchHit[] {
  const needle = fold(q);
  if (!needle) return [];
  const ranked: { t: IndexedTown; rank: number }[] = [];
  for (const t of index.towns) {
    const name = fold(t.name);
    let rank = -1;
    if (name.startsWith(needle)) rank = 0;
    else if (name.split(/[\s-]+/).some((w) => w.startsWith(needle))) rank = 1;
    else if (t.search.includes(needle)) rank = 2;
    if (rank >= 0) ranked.push({ t, rank });
  }
  ranked.sort((a, b) => a.rank - b.rank || (b.t.readiness ?? -1) - (a.t.readiness ?? -1) || a.t.name.localeCompare(b.t.name));
  return ranked.slice(0, Math.max(1, Math.min(limit, 50))).map(({ t }) => ({
    slug: t.slug,
    name: t.name,
    legal_type: t.legal_type,
    county: t.county,
    region: t.region,
    grade: t.grade,
    readiness: t.readiness,
  }));
}

export interface FilterParams {
  region?: string;
  county?: string;
  band?: "under_5000" | "5000_plus";
  grade?: string; // comma-separated letters
  min_readiness?: number;
  max_home_value?: number;
  max_drive_nyc?: number;
  max_drive_hub?: number;
  min_population?: number;
  max_population?: number;
  has_award?: boolean;
  sort?: "readiness" | "home_value" | "drive_nyc" | "population" | "name";
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

const NUMERIC: (keyof FilterParams)[] = ["min_readiness", "max_home_value", "max_drive_nyc", "max_drive_hub", "min_population", "max_population", "limit", "offset"];

/** Parses query-string values; unknown keys are ignored, bad numbers are errors. */
export function parseFilter(params: URLSearchParams): { ok: true; value: FilterParams } | { ok: false; error: string } {
  const out: FilterParams = {};
  for (const [k, v] of params) {
    if (NUMERIC.includes(k as keyof FilterParams)) {
      const n = Number(v);
      if (!Number.isFinite(n)) return { ok: false, error: `${k} must be a number` };
      (out as Record<string, unknown>)[k] = n;
    } else if (k === "has_award") out.has_award = v === "1" || v === "true";
    else if (k === "band") {
      if (v !== "under_5000" && v !== "5000_plus") return { ok: false, error: "band must be under_5000 or 5000_plus" };
      out.band = v;
    } else if (k === "sort") {
      if (!["readiness", "home_value", "drive_nyc", "population", "name"].includes(v)) return { ok: false, error: "unknown sort" };
      out.sort = v as FilterParams["sort"];
    } else if (k === "order") {
      if (v !== "asc" && v !== "desc") return { ok: false, error: "order must be asc or desc" };
      out.order = v;
    } else if (k === "region" || k === "county" || k === "grade") out[k] = v;
  }
  return { ok: true, value: out };
}

function usable(f: Fact | undefined): f is Fact & { value: number } {
  return !!f && f.value !== null && !f.suppressed;
}

export function filter(index: TownIndex, p: FilterParams): { total: number; towns: IndexedTown[] } {
  const grades = p.grade ? new Set(p.grade.toUpperCase().split(",").map((g) => g.trim())) : null;
  let rows = index.towns.filter((t) => {
    if (p.region && fold(t.region) !== fold(p.region)) return false;
    if (p.county && fold(t.county) !== fold(p.county)) return false;
    if (p.band && t.band !== p.band) return false;
    if (grades && !(t.grade && grades.has(t.grade))) return false;
    if (p.min_readiness !== undefined && !(t.readiness !== null && t.readiness >= p.min_readiness)) return false;
    if (p.max_home_value !== undefined) {
      const f = t.facts.median_home_value;
      if (!usable(f) || f.value > p.max_home_value) return false;
    }
    if (p.max_drive_nyc !== undefined) {
      const f = t.facts.drive_min_nyc;
      if (!usable(f) || f.value > p.max_drive_nyc) return false;
    }
    if (p.max_drive_hub !== undefined) {
      const f = t.facts.drive_min_regional_hub;
      if (!usable(f) || f.value > p.max_drive_hub) return false;
    }
    if (p.min_population !== undefined && !((t.population ?? 0) >= p.min_population)) return false;
    if (p.max_population !== undefined && !((t.population ?? Infinity) <= p.max_population)) return false;
    if (p.has_award !== undefined) {
      const f = t.facts.dri_award_amount;
      const has = usable(f) && f.value > 0;
      if (has !== p.has_award) return false;
    }
    return true;
  });
  const key = (t: IndexedTown): number | string => {
    switch (p.sort ?? "readiness") {
      case "home_value":
        return usable(t.facts.median_home_value) ? t.facts.median_home_value.value : -Infinity;
      case "drive_nyc":
        return usable(t.facts.drive_min_nyc) ? t.facts.drive_min_nyc.value : Infinity;
      case "population":
        return t.population ?? -Infinity;
      case "name":
        return t.name;
      default:
        return t.readiness ?? -Infinity;
    }
  };
  const order = p.order ?? (p.sort === "drive_nyc" || p.sort === "name" || p.sort === "home_value" ? "asc" : "desc");
  rows = rows.sort((a, b) => {
    const ka = key(a), kb = key(b);
    const c = typeof ka === "string" && typeof kb === "string" ? ka.localeCompare(kb) : (ka as number) - (kb as number);
    return order === "asc" ? c : -c;
  });
  const total = rows.length;
  const offset = Math.max(0, p.offset ?? 0);
  const limit = Math.max(1, Math.min(p.limit ?? 25, 148));
  return { total, towns: rows.slice(offset, offset + limit) };
}

export function compare(index: TownIndex, slugs: string[]): { found: IndexedTown[]; missing: string[] } {
  const wanted = slugs.map((s) => s.trim().toLowerCase()).filter(Boolean).slice(0, 3);
  const bySlug = new Map(index.towns.map((t) => [t.slug, t]));
  const found: IndexedTown[] = [];
  const missing: string[] = [];
  for (const s of wanted) {
    const t = bySlug.get(s);
    if (t) found.push(t);
    else missing.push(s);
  }
  return { found, missing };
}

/** Strips the search haystack before a town leaves the API. */
export function publicTown(t: IndexedTown): Omit<IndexedTown, "search"> {
  const { search: _search, ...rest } = t;
  return rest;
}
