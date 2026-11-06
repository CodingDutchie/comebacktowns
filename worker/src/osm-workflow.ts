/**
 * The OSM Workflow: the 148 Overpass queries as durable steps, run ahead of the scheduled
 * GitHub refresh so that pass finds the files present and only fills gaps.
 *
 * Each town is one step with its own retries; attempt n goes to server n in the manifest's
 * list (the configured Overpass server, then the fallback), so a busy primary hands the
 * retry to the other machine. A step that finds its file already stored returns at once,
 * which is what makes a re-run of a partly finished instance cheap. Documents and sidecars
 * are written exactly as the Python ingest writes them, under the same keys.
 *
 * Before the towns, one probe step asks each server for a single node and keeps only those
 * that answer with a current base and New York data. From Cloudflare's edge most public
 * Overpass servers refuse or time out and one serves a stale replica (probed 2026-11-06),
 * so when none is usable the instance completes at once with status "no usable server"
 * instead of burning eight minutes of retries; the Python ingest reaches other servers.
 */
import { NonRetryableError } from "cloudflare:workflows";
import { WorkflowEntrypoint, type WorkflowEvent, type WorkflowStep } from "cloudflare:workers";
import { PROBE_QUERY, QUERIES_PREFIX, classify, documentFor, isoDate, latestQueriesKey, metaFor, probeVerdict, rawKey, serverFor, sha256Hex, usableServers, type QueriesManifest, type RunSummary, type ServerProbe } from "./osm";

export interface OsmEnv {
  RAW: R2Bucket;
}

export interface OsmParams {
  /** Snapshot date to file under; defaults to the scheduled or trigger date (UTC). */
  as_of?: string;
}

const encoder = new TextEncoder();
const USER_AGENT = "Comeback Towns/0.1 (+https://comebacktowns.com; data@comebacktowns.com)";

export class OsmWorkflow extends WorkflowEntrypoint<OsmEnv, OsmParams> {
  async run(event: WorkflowEvent<OsmParams>, step: WorkflowStep): Promise<RunSummary> {
    const asOf = event.payload?.as_of ?? isoDate(event.schedule?.scheduledTime ?? event.timestamp.getTime());

    const { key: manifestKey, manifest } = await step.do("load the queries manifest", async () => {
      const listed = await this.env.RAW.list({ prefix: QUERIES_PREFIX });
      const key = latestQueriesKey(listed.objects.map((o) => o.key));
      if (!key) throw new NonRetryableError(`no ${QUERIES_PREFIX}*/queries.json in the bucket; run pipeline.cli osm-queries`);
      const object = await this.env.RAW.get(key);
      if (!object) throw new Error(`${key} vanished between list and get`);
      return { key, manifest: (await object.json()) as QueriesManifest };
    });

    const freshness = { asOf, maxAgeDays: manifest.max_base_age_days ?? 14 };
    const probes = await step.do("probe the servers", { retries: { limit: 0, delay: "1 second" }, timeout: "3 minutes" }, async () => {
      const results: ServerProbe[] = [];
      for (const server of manifest.servers) {
        const t0 = Date.now();
        try {
          const response = await fetch(server, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT },
            body: new URLSearchParams({ data: PROBE_QUERY }),
            signal: AbortSignal.timeout(20_000),
          });
          results.push(probeVerdict(server, response.status, await response.text(), freshness, Date.now() - t0));
        } catch (error) {
          results.push({ server, ok: false, base: null, reason: String(error).slice(0, 120), ms: Date.now() - t0 });
        }
      }
      return results;
    });
    const servers = usableServers(manifest.servers, probes);
    const summary: RunSummary = { as_of: asOf, manifest: manifestKey, towns: manifest.towns.length, stored: 0, present: 0, servers: {}, status: servers.length ? "fetched" : "no usable server", probes };
    if (!servers.length) return summary;
    const retries = Math.max(1, servers.length * manifest.retries_per_server) - 1;

    for (const town of manifest.towns) {
      const outcome = await step.do(
        `overpass ${town.slug}`,
        { retries: { limit: retries, delay: `${Math.round(manifest.backoff_seconds)} seconds`, backoff: "exponential" }, timeout: "5 minutes" },
        async (ctx) => {
          const key = rawKey(asOf, town.geoid);
          if (await this.env.RAW.head(key)) return { status: "present" as const, server: null };
          const server = serverFor(ctx.attempt, servers);
          // Polite pacing against a shared public server; wall time, not CPU.
          await new Promise((resolve) => setTimeout(resolve, manifest.min_interval_seconds * 1000));
          const response = await fetch(server, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT },
            body: new URLSearchParams({ data: town.query }),
          });
          const verdict = classify(response.status, await response.text(), freshness);
          if (!verdict.ok) {
            const message = `osm: ${town.slug} @ ${new URL(server).host}: ${verdict.reason}`;
            if (verdict.retryable) throw new Error(message);
            throw new NonRetryableError(message);
          }
          const body = encoder.encode(JSON.stringify(documentFor(town, verdict.payload, server)));
          await this.env.RAW.put(key, body, { httpMetadata: { contentType: "application/json" } });
          const meta = metaFor(key, server, body.byteLength, await sha256Hex(body), new Date());
          await this.env.RAW.put(`${key}.meta.json`, JSON.stringify(meta, null, 2), { httpMetadata: { contentType: "application/json" } });
          return { status: "stored" as const, server };
        },
      );
      if (outcome.status === "stored") {
        summary.stored += 1;
        const host = new URL(outcome.server!).host;
        summary.servers[host] = (summary.servers[host] ?? 0) + 1;
      } else {
        summary.present += 1;
      }
    }
    return summary;
  }
}
