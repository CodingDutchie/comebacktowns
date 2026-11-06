/**
 * Pure logic for the OSM Workflow (worker/src/osm-workflow.ts): manifest selection, key
 * layout, server rotation, response classification and the document and sidecar shapes.
 * Everything here mirrors pipeline/ingest/osm.py and pipeline/storage.py so the files the
 * Workflow writes are indistinguishable from the ones the Python ingest writes.
 */

export interface TownQuery {
  geoid: string;
  slug: string;
  polygon_parts: number;
  query: string;
}

export interface QueriesManifest {
  as_of: string;
  tiger_key: string;
  source_id: string;
  servers: string[];
  min_interval_seconds: number;
  retries_per_server: number;
  backoff_seconds: number;
  /** Optional so an older manifest still loads; the Python default is 14. */
  max_base_age_days?: number;
  towns: TownQuery[];
}

export const SOURCE_ID = "osm";
export const QUERIES_PREFIX = "raw/osm-queries/";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** The newest manifest key among the listed ones, by its snapshot date; null when none. */
export function latestQueriesKey(keys: string[]): string | null {
  let best: { date: string; key: string } | null = null;
  for (const key of keys) {
    if (!key.startsWith(QUERIES_PREFIX) || !key.endsWith("/queries.json")) continue;
    const date = key.slice(QUERIES_PREFIX.length).split("/")[0];
    if (!DATE_RE.test(date)) continue;
    if (!best || date > best.date) best = { date, key };
  }
  return best?.key ?? null;
}

/** raw/osm/{as_of}/{geoid}.json, as pipeline.storage.raw_key builds it. */
export function rawKey(asOf: string, geoid: string): string {
  return `raw/${SOURCE_ID}/${asOf}/${geoid}.json`;
}

/** The ISO date (UTC) a scheduled or manual run should file its snapshot under. */
export function isoDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/** Attempt 1 goes to the first server, attempt 2 to the next, round-robin: a busy primary
 * hands the retry to the fallback instead of waiting on itself. */
export function serverFor(attempt: number, servers: string[]): string {
  if (!servers.length) throw new Error("no Overpass servers in the manifest");
  return servers[(Math.max(1, attempt) - 1) % servers.length];
}

export type Classified =
  | { ok: true; payload: Record<string, unknown> }
  | { ok: false; retryable: boolean; reason: string };

/** Mirrors the Python rules: 5xx/429/408 and a "runtime error" remark are a busy server and
 * worth a retry, as is a server whose data is older than `freshness` allows (a stalled mirror); any other non-2xx is a bad query; a body without elements is an error. */
export function classify(status: number, body: string, freshness?: { asOf: string; maxAgeDays: number }): Classified {
  if (status === 408 || status === 425 || status === 429 || status >= 500) {
    return { ok: false, retryable: true, reason: `HTTP ${status}` };
  }
  if (status < 200 || status >= 300) {
    return { ok: false, retryable: false, reason: `HTTP ${status}` };
  }
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(body) as Record<string, unknown>;
  } catch {
    return { ok: false, retryable: true, reason: "response was not JSON" };
  }
  const remark = String(payload.remark ?? "");
  if (!("elements" in payload) || remark.toLowerCase().includes("error")) {
    const busy = remark.toLowerCase().includes("runtime error");
    return { ok: false, retryable: busy, reason: remark || "no elements in response" };
  }
  if (freshness) {
    const base = Date.parse(String((payload.osm3s as { timestamp_osm_base?: string } | undefined)?.timestamp_osm_base ?? ""));
    const cutoff = Date.parse(`${freshness.asOf}T00:00:00Z`) - freshness.maxAgeDays * 86_400_000;
    // A missing or unparseable stamp is not stale (NaN compares false), as in Python.
    if (base < cutoff) {
      return { ok: false, retryable: true, reason: `stale replica: data from ${new Date(base).toISOString()}` };
    }
  }
  return { ok: true, payload };
}

/** The stored document, field for field what pipeline/ingest/osm.py writes. */
export function documentFor(town: TownQuery, payload: Record<string, unknown>, server: string): Record<string, unknown> {
  return {
    geoid: town.geoid,
    slug: town.slug,
    polygon_parts: town.polygon_parts,
    query: town.query,
    server,
    osm3s: payload.osm3s ?? null,
    elements: payload.elements,
  };
}

/** The .meta.json sidecar, as pipeline.storage.write_meta writes it. */
export function metaFor(key: string, url: string, bytes: number, sha256: string, fetchedAt: Date): Record<string, unknown> {
  return {
    key,
    url,
    bytes,
    sha256,
    content_type: "application/json",
    fetched_at: fetchedAt.toISOString().replace(/\.\d{3}Z$/, "+00:00"),
  };
}

export async function sha256Hex(data: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", data as BufferSource);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** One node from a small box in the Hudson Valley: enough to show a server answers, holds
 * New York (a regional extract returns nothing) and reports a current base. */
export const PROBE_QUERY = "[out:json][timeout:25];node(42.07,-73.95,42.08,-73.94);out 1;";

export interface ServerProbe {
  server: string;
  ok: boolean;
  /** The server's osm3s.timestamp_osm_base when it answered, else null. */
  base: string | null;
  reason: string;
  ms: number;
}

/** The probe verdict for one server, from the same rules as a town query plus one more: an
 * answer with no elements means the mirror does not hold New York (a regional extract). */
export function probeVerdict(server: string, status: number, body: string, freshness: { asOf: string; maxAgeDays: number }, ms: number): ServerProbe {
  const verdict = classify(status, body, freshness);
  if (!verdict.ok) return { server, ok: false, base: null, reason: verdict.reason, ms };
  const base = String((verdict.payload.osm3s as { timestamp_osm_base?: string } | undefined)?.timestamp_osm_base ?? "") || null;
  const elements = verdict.payload.elements;
  if (!Array.isArray(elements) || elements.length === 0) return { server, ok: false, base, reason: "no data for New York", ms };
  return { server, ok: true, base, reason: "ok", ms };
}

/** The servers worth asking for this snapshot, in the manifest's order. */
export function usableServers(servers: string[], probes: ServerProbe[]): string[] {
  const ok = new Set(probes.filter((p) => p.ok).map((p) => p.server));
  return servers.filter((s) => ok.has(s));
}

export interface RunSummary {
  as_of: string;
  manifest: string;
  towns: number;
  stored: number;
  present: number;
  servers: Record<string, number>;
  /** "fetched" when at least one server was usable; "no usable server" ends the instance
   * cleanly in seconds so the Python ingest, which reaches other servers, does the work. */
  status: "fetched" | "no usable server";
  probes: ServerProbe[];
}
