/**
 * Pure planning logic for the refresh orchestrator: which stages a run has, what its
 * Workflow instance is called, and what the cron triggers mean. No I/O here, so it is unit
 * tested; the Workflow (refresh-workflow.ts) and the scheduled handler (index.ts) execute it.
 */
export type Kind = "monthly" | "annual" | "discover";

/** A job the container knows how to run (container/jobs.py is the whitelist on the other side). */
export type JobName = "ingest" | "osm_queries" | "validate" | "load" | "publish" | "discover";

export type Stage =
  | { type: "job"; id: string; job: JobName; params: Record<string, string | boolean>; timeoutMinutes: number; retries: number }
  | { type: "osm-workflow"; id: string; timeoutMinutes: number };

export const MONTHLY_SOURCES = ["gazetteer", "popest", "tiger", "zillow", "osm"] as const;
export const ANNUAL_SOURCES = ["gazetteer", "popest", "tiger", "acs", "permits", "nrhp", "rail", "hospitals", "osrm", "dri", "irs"] as const;

const SOURCE_NAME = /^[a-z][a-z0-9_]{0,31}$/;

export function isSourceName(name: string): boolean {
  return SOURCE_NAME.test(name);
}

export interface PlanOptions {
  kind: Kind;
  /** Score without seed/pilot_v0.csv (QA rule 4). Only for a manual run. */
  skipPilot?: boolean;
  /** For "discover": the sources whose newer years were found. */
  sources?: string[];
}

/** Ingest is idempotent (a rerun skips what is stored), so it may retry once; loads never retry. */
function ingest(source: string): Stage {
  return { type: "job", id: `ingest ${source}`, job: "ingest", params: { source }, timeoutMinutes: 45, retries: 1 };
}

export function buildPlan(opts: PlanOptions): Stage[] {
  const skipPilot = Boolean(opts.skipPilot);
  const tail: Stage[] = [
    { type: "job", id: "validate (dry runs)", job: "validate", params: { skip_pilot: skipPilot }, timeoutMinutes: 30, retries: 0 },
    { type: "job", id: "load", job: "load", params: { skip_pilot: skipPilot }, timeoutMinutes: 30, retries: 0 },
    { type: "job", id: "publish", job: "publish", params: {}, timeoutMinutes: 30, retries: 0 },
  ];
  if (opts.kind === "monthly") {
    const python = MONTHLY_SOURCES.filter((s) => s !== "osm");
    return [
      ...python.map(ingest),
      { type: "job", id: "osm queries", job: "osm_queries", params: {}, timeoutMinutes: 10, retries: 1 },
      { type: "osm-workflow", id: "osm workflow", timeoutMinutes: 90 },
      // The Python ingest after the Workflow stores only the towns the Workflow missed.
      ingest("osm"),
      ...tail,
    ];
  }
  if (opts.kind === "annual") return [...ANNUAL_SOURCES.map(ingest), ...tail];
  const sources = opts.sources ?? [];
  if (!sources.length) return [];
  const bad = sources.filter((s) => !isSourceName(s));
  if (bad.length) throw new Error(`unsafe source name(s): ${bad.join(", ")}`);
  return [...sources.map(ingest), ...tail];
}

/** `source<TAB>years` lines from `pipeline.cli discover`; only the source names are used. */
export function parseDiscovered(stdout: string): string[] {
  const names: string[] = [];
  for (const line of stdout.split("\n")) {
    const name = line.split("\t")[0]?.trim();
    if (name && isSourceName(name) && !names.includes(name)) names.push(name);
  }
  return names;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** Deterministic Workflow instance id: creating the same id twice is refused, which makes cron slots idempotent. */
export function instanceId(kind: Kind, at: Date): string {
  const y = at.getUTCFullYear();
  return kind === "annual" ? `annual-${y}` : `${kind}-${y}-${pad(at.getUTCMonth() + 1)}`;
}

export function okKey(kind: Kind, at: Date): string {
  return `refresh:ok:${instanceId(kind, at)}`;
}

export type CronAction = { type: "start"; kind: Kind } | { type: "watchdog" } | { type: "ignore" };

export function actionForCron(cron: string): CronAction {
  switch (cron) {
    case "0 9 2 * *":
    case "0 15 2 * *":
      return { type: "start", kind: "monthly" };
    case "0 9 3 * *":
      return { type: "start", kind: "discover" };
    case "0 9 15 1 *":
      return { type: "start", kind: "annual" };
    case "30 10 3 * *":
      return { type: "watchdog" };
    default:
      return { type: "ignore" };
  }
}

export const ISSUE_LABEL = "refresh-failure";

export function issueTitle(kind: Kind | "watchdog", stage: string): string {
  return `refresh ${kind} failed: ${stage}`;
}

/** Remove secret values from text that is about to be logged or put in an issue. */
export function scrub(text: string, secrets: Array<string | undefined>): string {
  let out = text;
  for (const s of secrets) if (s && s.length >= 6) out = out.split(s).join("***");
  return out;
}

export interface JobStatus {
  state: "running" | "ok" | "failed";
  exit_code: number | null;
  log_tail: string;
  stdout: string;
}
