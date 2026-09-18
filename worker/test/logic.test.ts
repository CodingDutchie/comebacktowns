import { describe, expect, it } from "vitest";
import { buildIndex, compare, filter, parseFilter, publicTown, search, type MetricRow, type ScoreRow, type TownRow } from "../src/logic";

const towns: TownRow[] = [
  { geoid: "3613002", name: "Catskill", legal_type: "village", county: "Greene", region: "Capital Region", lat: 42.2, lon: -73.9, pop_latest: 3723, slug: "catskill-ny" },
  { geoid: "3639727", name: "Kingston", legal_type: "city", county: "Ulster", region: "Hudson Valley", lat: 41.9, lon: -74.0, pop_latest: 24100, slug: "kingston-ny" },
  { geoid: "3636277", name: "Hudson", legal_type: "city", county: "Columbia", region: "Capital Region", lat: 42.25, lon: -73.79, pop_latest: 5900, slug: "hudson-ny" },
  { geoid: "3643335", name: "Little Falls", legal_type: "city", county: "Herkimer", region: "Mohawk Valley", lat: 43.0, lon: -74.8, pop_latest: 4600, slug: "little-falls-ny" },
];
const scores: ScoreRow[] = [
  { geoid: "3613002", readiness: 77.9, grade: "A", coverage: 0.92, factor_scores: '{"access":0.69}', computed_at: "2026-09-18T19:00:00" },
  { geoid: "3613002", readiness: 50, grade: "C", coverage: 0.9, factor_scores: "{}", computed_at: "2026-09-18T10:00:00" }, // older run, ignored
  { geoid: "3639727", readiness: 70.1, grade: "B", coverage: 1, factor_scores: "{}", computed_at: "2026-09-18T19:00:00" },
  { geoid: "3636277", readiness: 60, grade: "C", coverage: 1, factor_scores: "{}", computed_at: "2026-09-18T19:00:00" },
];
const metrics: MetricRow[] = [
  { geoid: "3613002", metric: "median_home_value", period: "2020-2024", value: 242500, suppressed: 0 },
  { geoid: "3613002", metric: "drive_min_nyc", period: "2026-08", value: 200, suppressed: 0 },
  { geoid: "3613002", metric: "drive_min_nyc", period: "2026-09", value: 154.1, suppressed: 0 },
  { geoid: "3613002", metric: "dri_award_amount", period: "2016-2025", value: 10000000, suppressed: 0 },
  { geoid: "3639727", metric: "median_home_value", period: "2020-2024", value: 320000, suppressed: 0 },
  { geoid: "3639727", metric: "drive_min_nyc", period: "2026-09", value: 110, suppressed: 0 },
  { geoid: "3639727", metric: "dri_award_amount", period: "2016-2025", value: 0, suppressed: 0 },
  { geoid: "3636277", metric: "median_home_value", period: "2020-2024", value: 300000, suppressed: 1 },
  { geoid: "3636277", metric: "drive_min_nyc", period: "2026-09", value: 150, suppressed: 0 },
];
const index = buildIndex(towns, scores, metrics, () => "now");

describe("buildIndex", () => {
  it("keeps the latest scores run and the latest period per metric", () => {
    const c = index.towns.find((t) => t.slug === "catskill-ny")!;
    expect(c.readiness).toBe(77.9);
    expect(c.facts.drive_min_nyc).toEqual({ value: 154.1, period: "2026-09", suppressed: false });
    expect(c.band).toBe("under_5000");
    expect(index.computed_at).toBe("2026-09-18T19:00:00");
    expect(index.towns.find((t) => t.slug === "little-falls-ny")!.readiness).toBeNull();
  });
});

describe("search", () => {
  it("ranks name prefix, then word prefix, then substring", () => {
    expect(search(index, "hu").map((h) => h.slug)).toEqual(["hudson-ny"]);
    expect(search(index, "falls").map((h) => h.slug)).toEqual(["little-falls-ny"]);
    expect(search(index, "greene").map((h) => h.slug)).toEqual(["catskill-ny"]);
    expect(search(index, "  ")).toEqual([]);
    expect(search(index, "CATS")[0].grade).toBe("A");
  });
  it("respects the limit", () => {
    expect(search(index, "n", 2)).toHaveLength(2);
  });
});

describe("filter", () => {
  it("applies region, band, grade and numeric bounds", () => {
    expect(filter(index, { region: "capital region" }).towns.map((t) => t.slug)).toEqual(["catskill-ny", "hudson-ny"]);
    expect(filter(index, { band: "5000_plus", grade: "b,c" }).towns.map((t) => t.slug)).toEqual(["kingston-ny", "hudson-ny"]);
    expect(filter(index, { max_home_value: 250000 }).towns.map((t) => t.slug)).toEqual(["catskill-ny"]);
    // a suppressed home value never satisfies a price filter
    expect(filter(index, { max_home_value: 999999 }).towns.map((t) => t.slug)).not.toContain("hudson-ny");
    expect(filter(index, { max_drive_nyc: 120 }).towns.map((t) => t.slug)).toEqual(["kingston-ny"]);
    expect(filter(index, { has_award: true }).towns.map((t) => t.slug)).toEqual(["catskill-ny"]);
    expect(filter(index, { min_readiness: 60 }).total).toBe(3);
  });
  it("sorts and pages", () => {
    expect(filter(index, { sort: "drive_nyc" }).towns.map((t) => t.slug)).toEqual(["kingston-ny", "hudson-ny", "catskill-ny", "little-falls-ny"]);
    expect(filter(index, { sort: "name", limit: 2, offset: 1 }).towns.map((t) => t.slug)).toEqual(["hudson-ny", "kingston-ny"]);
    expect(filter(index, {}).towns[0].slug).toBe("catskill-ny"); // readiness desc by default
  });
  it("parses and rejects bad params", () => {
    expect(parseFilter(new URLSearchParams("max_home_value=abc"))).toEqual({ ok: false, error: "max_home_value must be a number" });
    expect(parseFilter(new URLSearchParams("band=huge"))).toMatchObject({ ok: false });
    expect(parseFilter(new URLSearchParams("region=Mohawk%20Valley&limit=5&has_award=1&junk=x"))).toEqual({ ok: true, value: { region: "Mohawk Valley", limit: 5, has_award: true } });
  });
});

describe("compare", () => {
  it("returns up to three towns and names the missing ones", () => {
    const r = compare(index, ["catskill-ny", "nowhere-ny", "hudson-ny", "kingston-ny", "little-falls-ny"]);
    expect(r.found.map((t) => t.slug)).toEqual(["catskill-ny", "hudson-ny"]);
    expect(r.missing).toEqual(["nowhere-ny"]);
    expect("search" in publicTown(r.found[0])).toBe(false);
  });
});
