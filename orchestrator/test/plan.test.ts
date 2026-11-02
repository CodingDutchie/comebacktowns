import { describe, expect, it } from "vitest";
import { actionForCron, buildPlan, instanceId, isSourceName, issueTitle, okKey, parseDiscovered, scrub } from "../src/plan";

describe("buildPlan", () => {
  it("monthly: python ingests, queries, the OSM Workflow, the gap-filling ingest, then validate before load before publish", () => {
    const ids = buildPlan({ kind: "monthly" }).map((s) => s.id);
    expect(ids).toEqual(["ingest gazetteer", "ingest popest", "ingest tiger", "ingest zillow", "osm queries", "osm workflow", "ingest osm", "validate (dry runs)", "load", "publish"]);
  });
  it("annual: every annual source, no OSM", () => {
    const ids = buildPlan({ kind: "annual" }).map((s) => s.id);
    expect(ids.filter((i) => i.startsWith("ingest")).length).toBe(11);
    expect(ids).not.toContain("osm workflow");
    expect(ids.slice(-3)).toEqual(["validate (dry runs)", "load", "publish"]);
  });
  it("never retries a load or publish", () => {
    for (const s of buildPlan({ kind: "monthly" })) {
      if (s.type === "job" && ["validate", "load", "publish"].includes(s.job)) expect(s.retries).toBe(0);
    }
  });
  it("discover with nothing found plans nothing", () => {
    expect(buildPlan({ kind: "discover", sources: [] })).toEqual([]);
  });
  it("discover refuses an unsafe source name", () => {
    expect(() => buildPlan({ kind: "discover", sources: ["permits; rm -rf /"] })).toThrow(/unsafe/);
  });
  it("passes skip_pilot to validate and load only", () => {
    const plan = buildPlan({ kind: "annual", skipPilot: true });
    const flagged = plan.filter((s) => s.type === "job" && s.params.skip_pilot === true).map((s) => s.id);
    expect(flagged).toEqual(["validate (dry runs)", "load"]);
  });
});

describe("parseDiscovered", () => {
  it("reads source names from tab-separated lines and ignores noise", () => {
    expect(parseDiscovered("permits\t2025\nirs\t2023 2024\n\nINFO something odd\nirs\t2024\n")).toEqual(["permits", "irs"]);
  });
});

describe("ids and crons", () => {
  const at = new Date("2026-12-02T09:00:00Z");
  it("derives deterministic instance ids", () => {
    expect(instanceId("monthly", at)).toBe("monthly-2026-12");
    expect(instanceId("discover", at)).toBe("discover-2026-12");
    expect(instanceId("annual", new Date("2027-01-15T09:00:00Z"))).toBe("annual-2027");
    expect(okKey("monthly", at)).toBe("refresh:ok:monthly-2026-12");
  });
  it("maps each cron string to an action", () => {
    expect(actionForCron("0 9 2 * *")).toEqual({ type: "start", kind: "monthly" });
    expect(actionForCron("0 15 2 * *")).toEqual({ type: "start", kind: "monthly" });
    expect(actionForCron("0 9 3 * *")).toEqual({ type: "start", kind: "discover" });
    expect(actionForCron("0 9 15 1 *")).toEqual({ type: "start", kind: "annual" });
    expect(actionForCron("30 10 3 * *")).toEqual({ type: "watchdog" });
    expect(actionForCron("* * * * *")).toEqual({ type: "ignore" });
  });
  it("keeps the crons in wrangler.toml and the handler in step", async () => {
    const { default: toml } = await import("../wrangler.toml?raw");
    const crons = [...toml.match(/crons = \[(.*)\]/)![1]!.matchAll(/"([^"]+)"/g)].map((m) => m[1]!);
    expect(crons.length).toBe(5);
    for (const c of crons) expect(actionForCron(c).type).not.toBe("ignore");
  });
});

describe("helpers", () => {
  it("validates source names", () => {
    expect(isSourceName("permits")).toBe(true);
    expect(isSourceName("Permits")).toBe(false);
    expect(isSourceName("a b")).toBe(false);
  });
  it("scrubs secret values and ignores short or missing ones", () => {
    expect(scrub("token=abcdef123456 ok", ["abcdef123456", undefined, "ab"])).toBe("token=*** ok");
  });
  it("titles issues like the old workflows did", () => {
    expect(issueTitle("monthly", "ingest tiger")).toBe("refresh monthly failed: ingest tiger");
  });
});
