import { describe, expect, it } from "vitest";
import { classify, documentFor, isoDate, latestQueriesKey, metaFor, rawKey, serverFor, sha256Hex, type TownQuery } from "../src/osm";

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
