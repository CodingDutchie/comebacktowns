/**
 * comebacktowns.com Worker: serves the static site from assets and a small JSON API.
 *
 *   GET /api/search?q=            search-as-you-type over name, county and slug
 *   GET /api/filter?region=&band=&grade=&min_readiness=&max_home_value=&max_drive_nyc=…
 *   GET /api/compare?towns=a,b,c  up to three towns, every headline fact
 *   GET /api/health
 *
 * The town index (towns + latest scores + latest facts) is built from D1 once and cached in
 * KV for INDEX_TTL seconds, so a search never waits on the database. Responses carry
 * Cache-Control so the edge cache serves repeated queries without running the Worker.
 */
import { buildIndex, compare, filter, parseFilter, publicTown, search, type MetricRow, type ScoreRow, type TownIndex, type TownRow, FACT_METRICS } from "./logic";

export interface Env {
  DB: D1Database;
  CACHE: KVNamespace;
  ASSETS: Fetcher;
  SITE_ORIGINS: string; // comma-separated allowed origins for CORS
  INDEX_TTL?: string;
}

const INDEX_KEY = "index:v1";
const DEFAULT_TTL = 600;

let memo: { index: TownIndex; expires: number } | null = null; // per-isolate memo, KV behind it

async function loadIndex(env: Env, ctx: ExecutionContext): Promise<TownIndex> {
  const now = Date.now();
  if (memo && memo.expires > now) return memo.index;
  const ttl = Number(env.INDEX_TTL ?? DEFAULT_TTL);
  const cached = await env.CACHE.get<TownIndex>(INDEX_KEY, "json");
  if (cached) {
    memo = { index: cached, expires: now + Math.min(ttl, 60) * 1000 };
    return cached;
  }
  const index = await buildFromD1(env);
  memo = { index, expires: now + Math.min(ttl, 60) * 1000 };
  ctx.waitUntil(env.CACHE.put(INDEX_KEY, JSON.stringify(index), { expirationTtl: ttl }));
  return index;
}

async function buildFromD1(env: Env): Promise<TownIndex> {
  const placeholders = FACT_METRICS.map(() => "?").join(",");
  const [towns, scores, metrics] = await Promise.all([
    env.DB.prepare("SELECT geoid, name, legal_type, county, region, lat, lon, pop_latest, slug FROM towns").all<TownRow>(),
    env.DB.prepare("SELECT geoid, readiness, grade, coverage, factor_scores, computed_at FROM scores WHERE config_version = 'v1'").all<ScoreRow>(),
    env.DB.prepare(`SELECT geoid, metric, period, value, suppressed FROM metrics WHERE metric IN (${placeholders})`).bind(...FACT_METRICS).all<MetricRow>(),
  ]);
  return buildIndex(towns.results, scores.results, metrics.results);
}

function corsHeaders(request: Request, env: Env): Record<string, string> {
  const origin = request.headers.get("Origin");
  const allowed = (env.SITE_ORIGINS ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  const headers: Record<string, string> = { Vary: "Origin" };
  if (origin && allowed.includes(origin)) {
    headers["Access-Control-Allow-Origin"] = origin;
    headers["Access-Control-Allow-Methods"] = "GET, OPTIONS";
    headers["Access-Control-Allow-Headers"] = "Accept";
    headers["Access-Control-Max-Age"] = "86400";
  }
  return headers;
}

function json(
  body: unknown,
  request: Request,
  env: Env,
  status = 200,
  maxAge = 300,
  startedAt?: number,
): Response {
  const headers: Record<string, string> = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": status === 200 ? `public, max-age=${maxAge}, s-maxage=${maxAge}` : "no-store",
    "X-Content-Type-Options": "nosniff",
    ...corsHeaders(request, env),
  };
  // Wall time spent in the Worker for this request, so latency can be read at the edge
  // independent of the caller's network path.
  if (startedAt !== undefined) headers["Server-Timing"] = `worker;dur=${Date.now() - startedAt}`;
  return new Response(JSON.stringify(body), { status, headers });
}

async function api(request: Request, env: Env, ctx: ExecutionContext, url: URL): Promise<Response> {
  const t0 = Date.now();
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: corsHeaders(request, env) });
  if (request.method !== "GET" && request.method !== "HEAD") {
    return json({ error: "method not allowed" }, request, env, 405);
  }
  const path = url.pathname.replace(/\/+$/, "");
  if (path === "/api/health") {
    const index = await loadIndex(env, ctx);
    return json({ ok: true, towns: index.towns.length, scores_computed_at: index.computed_at, index_built_at: index.built_at }, request, env, 200, 30, t0);
  }
  if (path === "/api/search") {
    const q = url.searchParams.get("q") ?? "";
    if (q.length > 80) return json({ error: "q too long" }, request, env, 400);
    const index = await loadIndex(env, ctx);
    const limit = Number(url.searchParams.get("limit") ?? 10);
    return json({ q, results: search(index, q, Number.isFinite(limit) ? limit : 10) }, request, env, 200, 300, t0);
  }
  if (path === "/api/filter") {
    const parsed = parseFilter(url.searchParams);
    if (!parsed.ok) return json({ error: parsed.error }, request, env, 400);
    const index = await loadIndex(env, ctx);
    const { total, towns } = filter(index, parsed.value);
    return json({ total, count: towns.length, towns: towns.map(publicTown) }, request, env, 200, 300, t0);
  }
  if (path === "/api/compare") {
    const slugs = (url.searchParams.get("towns") ?? "").split(",");
    const index = await loadIndex(env, ctx);
    const { found, missing } = compare(index, slugs);
    if (!found.length) return json({ error: "no matching towns", missing }, request, env, 404);
    return json({ towns: found.map(publicTown), missing }, request, env, 200, 300, t0);
  }
  return json({ error: "not found" }, request, env, 404);
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    // www -> apex, permanently
    if (url.hostname.startsWith("www.")) {
      url.hostname = url.hostname.slice(4);
      return Response.redirect(url.toString(), 301);
    }
    if (url.pathname === "/api" || url.pathname.startsWith("/api/")) {
      try {
        return await api(request, env, ctx, url);
      } catch (err) {
        console.error("api error", (err as Error).message);
        return json({ error: "internal error" }, request, env, 500);
      }
    }
    return env.ASSETS.fetch(request);
  },
} satisfies ExportedHandler<Env>;
