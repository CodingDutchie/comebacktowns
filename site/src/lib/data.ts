/**
 * Build-time data access. `site/data/` is written by `python -m pipeline.cli export` and is
 * gitignored; when it is absent (CI, a fresh clone) the committed `site/sample-data/`
 * fixture is used so templates still build.
 */
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export interface Town {
  geoid: string;
  name: string;
  legal_type: string;
  county: string;
  county_fips: string;
  region: string;
  lat: number;
  lon: number;
  pop_latest: number | null;
  pop_latest_year: number | null;
  slug: string;
}

export interface MetricEntry {
  period: string;
  value: number | null;
  moe: number | null;
  suppressed: boolean;
  source_id: string;
  as_of: string;
  r2_key: string;
}

export interface ScoreInput {
  metric: string;
  value: number | null;
  period: string | null;
  source_id: string | null;
  r2_key: string | null;
  as_of: string | null;
  suppressed: boolean;
  status: "usable" | "suppressed" | "missing" | "not_applicable";
  normalised: number | null;
  contribution: number | null;
}

export interface Score {
  readiness: number;
  grade: string | null;
  coverage: number;
  computed_at: string;
  config_version: string;
  factor_scores: Record<string, number | null>;
  inputs: Record<string, ScoreInput>;
}

export interface MethodologyInput {
  name: string;
  metric: string;
  context_only: boolean;
  curve: string | null;
  conditional: boolean;
}

export interface Methodology {
  version: string;
  factors: { name: string; weight: number; inputs: MethodologyInput[] }[];
  grading: { method: string; bands: Record<string, number>; curve_within: string; population_band_split: number };
  min_coverage: number;
  suppression: { moe_threshold: number; text: string };
  bounds: Record<string, [number, number]>;
  metrics: Record<string, { label: string; format: string; description: string; key_number?: number }>;
}

export interface Source {
  id: string;
  name: string;
  publisher: string;
  licence: string;
  attribution: string;
  cadence: string;
  used_for: string;
  url: string;
  last_pull: string | null;
}

export interface Meta {
  generated_at: string;
  site: { SITE_NAME: string; SITE_DOMAIN: string; CONTACT_EMAIL: string; TAGLINE: string; STATE_ABBR: string };
  town_count: number;
  scored_count: number;
}

function dataDir(): URL {
  const real = new URL("../../data/", import.meta.url);
  if (existsSync(fileURLToPath(new URL("towns.json", real)))) return real;
  return new URL("../../sample-data/", import.meta.url);
}

function load<T>(name: string): T {
  return JSON.parse(readFileSync(fileURLToPath(new URL(name, dataDir())), "utf8")) as T;
}

export const towns: Town[] = load<Town[]>("towns.json");
export const metrics: Record<string, Record<string, MetricEntry>> = load("metrics.json");
export const scores: Record<string, Score> = load("scores.json");
export const methodology: Methodology = load("methodology.json");
export const sources: Source[] = load("sources.json");
export const meta: Meta = load("meta.json");
export const usingSampleData = !existsSync(fileURLToPath(new URL("../../data/towns.json", import.meta.url)));

export const townBySlug = new Map(towns.map((t) => [t.slug, t]));
export const sourceById = new Map(sources.map((s) => [s.id, s]));

export function metric(geoid: string, name: string): MetricEntry | undefined {
  return metrics[geoid]?.[name];
}

export function usable(entry: MetricEntry | undefined): entry is MetricEntry & { value: number } {
  return !!entry && entry.value !== null && !entry.suppressed;
}

export function band(town: Town): string {
  const split = methodology.grading.population_band_split;
  return (town.pop_latest ?? 0) < split ? `under ${split.toLocaleString("en-US")}` : `${split.toLocaleString("en-US")} and over`;
}

export function bandKey(town: Town): "small" | "large" {
  return (town.pop_latest ?? 0) < methodology.grading.population_band_split ? "small" : "large";
}

export const factorLabels: Record<string, string> = {
  access: "Access",
  building_stock: "Building stock",
  main_street: "Main street",
  price_headroom: "Price headroom",
  services: "Services",
  civic_capacity: "Civic capacity",
};

export const factorBlurbs: Record<string, string> = {
  access: "How easy it is to reach the city, a regional hub and a train.",
  building_stock: "Whether there is a pre-war fabric worth restoring.",
  main_street: "How much storefront activity already exists per resident.",
  price_headroom: "Whether prices leave room to rise without having already been found.",
  services: "Broadband, families with children, and a hospital within reach.",
  civic_capacity: "Whether the state has backed the downtown with a revitalization award.",
};
