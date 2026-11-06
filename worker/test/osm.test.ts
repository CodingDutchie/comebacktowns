import { describe, expect, it } from "vitest";
import { classify, documentFor, isoDate, latestQueriesKey, metaFor, probeVerdict, rawKey, serverFor, sha256Hex, usableServers, type TownQuery } from "../src/osm";

const town: TownQuery = { geoid: "3613002", slug: "catskill-ny", polygon_parts: 2, query: '[out:json];nwr["shop"](poly:"42.2 -73.87");out tags center;' };

describe("latestQueriesKey", () => {
  it("picks the newest dated manifest and ignores sidecars and strays", () => {
    const keys = [
      "raw/osm-queries/2026-09-18/queries.json",
      "raw/osm-queries/2026-09-18/queries.json.meta.json",
      "raw/osm-queries/2026-10-02/queries.json",
      "raw/osm-queries/notadate/queries.json",
      "raw/osm/2026-10-02/3613002.json",
    ];
    expect(latestQueriesKey(keys)).toBe("raw/osm-queries/2026-10-02/queries.json");
    expect(latestQueriesKey([])).toBeNull();
  });
});

describe("keys and dates", () => {
  it("files under the Python key layout and the UTC date", () => {
    expect(rawKey("2026-11-02", "3613002")).toBe("raw/osm/2026-11-02/3613002.json");
    expect(isoDate(Date.UTC(2026, 10, 2, 3, 0, 0))).toBe("2026-11-02");
  });
});

describe("serverFor", () => {
  it("rotates attempts across the manifest's servers", () => {
    const servers = ["https://a/api", "https://b/api"];
    expect(serverFor(1, servers)).toBe("https://a/api");
    expect(serverFor(2, servers)).toBe("https://b/api");
    expect(serverFor(3, servers)).toBe("https://a/api");
    expect(serverFor(0, servers)).toBe("https://a/api");
    expect(() => serverFor(1, [])).toThrow();
  });
});

describe("classify", () => {
  it("treats a busy server as retryable and a bad query as not", () => {
    expect(classify(504, "")).toEqual({ ok: false, retryable: true, reason: "HTTP 504" });
    expect(classify(429, "")).toEqual({ ok: false, retryable: true, reason: "HTTP 429" });
    expect(classify(400, "parse error")).toEqual({ ok: false, retryable: false, reason: "HTTP 400" });
  });
  it("reads an Overpass remark the way the Python ingest does", () => {
    const busy = classify(200, JSON.stringify({ remark: 'runtime error: Query timed out in "query"', elements: [] }));
    expect(busy).toEqual({ ok: false, retryable: true, reason: 'runtime error: Query timed out in "query"' });
    expect(classify(200, JSON.stringify({ remark: "some other error", elements: [] }))).toMatchObject({ ok: false, retryable: false });
    expect(classify(200, JSON.stringify({ osm3s: {} }))).toMatchObject({ ok: false, retryable: false, reason: "no elements in response" });
    expect(classify(200, "<html>")).toMatchObject({ ok: false, retryable: true });
    const good = classify(200, JSON.stringify({ osm3s: { timestamp_osm_base: "x" }, elements: [{ type: "node", id: 1, tags: { shop: "bakery" } }] }));
    expect(good.ok).toBe(true);
  });
});

describe("classify freshness", () => {
  const fresh = { asOf: "2026-11-02", maxAgeDays: 14 };
  const body = (base: string) => JSON.stringify({ osm3s: { timestamp_osm_base: base }, elements: [{ type: "node", id: 1, tags: { shop: "x" } }] });
  it("retries a stalled mirror whose data predates the window, so the next server is asked", () => {
    expect(classify(200, body("2026-08-10T00:10:23Z"), fresh)).toMatchObject({ ok: false, retryable: true });
    expect(classify(200, body("2026-11-02T18:40:18Z"), fresh).ok).toBe(true);
    expect(classify(200, body("2026-10-19T00:00:00Z"), fresh).ok).toBe(true);
    expect(classify(200, body("2026-10-18T23:59:59Z"), fresh).ok).toBe(false);
  });
  it("does not treat a missing or unparseable stamp as stale", () => {
    expect(classify(200, body("x"), fresh).ok).toBe(true);
    expect(classify(200, JSON.stringify({ elements: [] }), fresh).ok).toBe(true);
  });
});

describe("document and sidecar", () => {
  it("matches the Python shapes field for field", async () => {
    const payload = { osm3s: { timestamp_osm_base: "2026-10-01T00:00:00Z" }, elements: [{ type: "node", id: 1, tags: { shop: "bakery" } }] };
    const doc = documentFor(town, payload, "https://overpass-api.de/api/interpreter");
    expect(Object.keys(doc)).toEqual(["geoid", "slug", "polygon_parts", "query", "server", "osm3s", "elements"]);
    expect(doc.elements).toBe(payload.elements);
    const body = new TextEncoder().encode(JSON.stringify(doc));
    const meta = metaFor("raw/osm/2026-11-02/3613002.json", "https://overpass-api.de/api/interpreter", body.byteLength, await sha256Hex(body), new Date(Date.UTC(2026, 10, 2, 3, 4, 5)));
    expect(Object.keys(meta)).toEqual(["key", "url", "bytes", "sha256", "content_type", "fetched_at"]);
    expect(meta.fetched_at).toBe("2026-11-02T03:04:05+00:00");
    expect(String(meta.sha256)).toMatch(/^[0-9a-f]{64}$/);
  });
});

describe("server probe", () => {
  const fresh = { asOf: "2026-11-06", maxAgeDays: 14 };
  const node = JSON.stringify({ osm3s: { timestamp_osm_base: "2026-11-06T10:00:00Z" }, elements: [{ type: "node", id: 1 }] });
  it("keeps a server that answers with a current base and New York data", () => {
    expect(probeVerdict("https://a/api", 200, node, fresh, 300)).toEqual({ server: "https://a/api", ok: true, base: "2026-11-06T10:00:00Z", reason: "ok", ms: 300 });
  });
  it("drops a stale replica, a refused connection and a regional extract", () => {
    const stale = JSON.stringify({ osm3s: { timestamp_osm_base: "2026-08-10T00:10:23Z" }, elements: [{ type: "node", id: 1 }] });
    expect(probeVerdict("https://fr/api", 200, stale, fresh, 400)).toMatchObject({ ok: false, reason: "stale replica: data from 2026-08-10T00:10:23.000Z" });
    expect(probeVerdict("https://de/api", 521, "error code: 521", fresh, 19000)).toMatchObject({ ok: false, base: null, reason: "HTTP 521" });
    const swiss = JSON.stringify({ osm3s: { timestamp_osm_base: "2026-11-06T10:00:00Z" }, elements: [] });
    expect(probeVerdict("https://ch/api", 200, swiss, fresh, 400)).toMatchObject({ ok: false, reason: "no data for New York" });
  });
  it("keeps the manifest's order among the usable servers", () => {
    const servers = ["https://fr/api", "https://z/api", "https://a/api"];
    const probes = [
      probeVerdict("https://a/api", 200, node, fresh, 1),
      probeVerdict("https://fr/api", 521, "", fresh, 1),
      probeVerdict("https://z/api", 200, node, fresh, 1),
    ];
    expect(usableServers(servers, probes)).toEqual(["https://z/api", "https://a/api"]);
    expect(usableServers(servers, probes.map((p) => ({ ...p, ok: false })))).toEqual([]);
  });
});
