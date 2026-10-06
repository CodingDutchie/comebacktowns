/**
 * The OSM Workflow: the 148 Overpass queries as durable steps, run ahead of the scheduled
 * GitHub refresh so that pass finds the files present and only fills gaps.
 *
 * Each town is one step with its own retries; attempt n goes to server n in the manifest's
 * list (the configured Overpass server, then the fallback), so a busy primary hands the
 * retry to the other machine. A step that finds its file already stored returns at once,
 * which is what makes a re-run of a partly finished instance cheap. Documents and sidecars
 * are written exactly as the Python ingest writes them, under the same keys.
 */
import { NonRetryableError } from "cloudflare:workflows";
import { WorkflowEntrypoint, type WorkflowEvent, type WorkflowStep } from "cloudflare:workers";
import { QUERIES_PREFIX, classify, documentFor, isoDate, latestQueriesKey, metaFor, rawKey, serverFor, sha256Hex, type QueriesManifest, type RunSummary } from "./osm";

export interface OsmEnv {
  RAW: R2Bucket;
}

export interface OsmParams {
  /** Snapshot date to file under; defaults to the scheduled or trigger date (UTC). */
  as_of?: string;
}

const encoder = new TextEncoder();

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

    const summary: RunSummary = { as_of: asOf, manifest: manifestKey, towns: manifest.towns.length, stored: 0, present: 0, servers: {} };
    const retries = Math.max(1, manifest.servers.length * manifest.retries_per_server) - 1;

    for (const town of manifest.towns) {
      const outcome = await step.do(
        `overpass ${town.slug}`,
        { retries: { limit: retries, delay: `${Math.round(manifest.backoff_seconds)} seconds`, backoff: "exponential" }, timeout: "5 minutes" },
        async (ctx) => {
          const key = rawKey(asOf, town.geoid);
          if (await this.env.RAW.head(key)) return { status: "present" as const, server: null };
          const server = serverFor(ctx.attempt, manifest.servers);
          // Polite pacing against a shared public server; wall time, not CPU.
          await new Promise((resolve) => setTimeout(resolve, manifest.min_interval_seconds * 1000));
          const response = await fetch(server, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Comeback Towns/0.1 (+https://comebacktowns.com; data@comebacktowns.com)" },
            body: new URLSearchParams({ data: town.query }),
          });
          const verdict = classify(response.status, await response.text());
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
