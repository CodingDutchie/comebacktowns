#!/usr/bin/env node
/**
 * launch-check: probe a live site for the indexing and analytics mistakes that
 * kept recurring across the portfolio (Oct 2026). Plain HTTP, no dependencies.
 *
 *   node check.mjs https://example.com            # human-readable, exit 1 on any FAIL
 *   node check.mjs https://example.com --json     # machine-readable
 *   node check.mjs https://example.com --pages 50 # sample more sitemap URLs (default 25)
 *   node check.mjs https://example.com --alias foo.pages.dev   # extra host that must redirect (repeatable)
 *
 * With CLOUDFLARE_API_TOKEN and CF_ACCOUNT_ID (or CLOUDFLARE_ACCOUNT_ID) it also
 * looks up the site's own pages.dev / workers.dev addresses and its Web
 * Analytics sites; without them those checks are skipped and say so.
 *
 * Every FAIL and WARN names a recipe (R1…R10) in SKILL.md with the fix.
 */

const args = process.argv.slice(2);
const target = args.find((a) => /^https?:\/\//.test(a));
if (!target) {
  console.error('usage: node check.mjs https://example.com [--json] [--pages N]');
  process.exit(2);
}
const JSON_OUT = args.includes('--json');
const PAGES = Number(args[args.indexOf('--pages') + 1]) || 25;
const ALIASES = args.flatMap((a, i) => (a === '--alias' && args[i + 1] ? [args[i + 1].replace(/^https?:\/\//, '').replace(/\/.*$/, '')] : []));
const CF_TOKEN = process.env.CLOUDFLARE_API_TOKEN;
const CF_ACCOUNT = process.env.CF_ACCOUNT_ID || process.env.CLOUDFLARE_ACCOUNT_ID;
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36';
const TITLE_MAX = 60;

const results = [];
const add = (level, id, msg, recipe) => results.push({ level, id, msg, recipe });

async function req(url, { method = 'GET', follow = false } = {}) {
  try {
    const res = await fetch(url, {
      method,
      redirect: follow ? 'follow' : 'manual',
      headers: { 'user-agent': UA, accept: 'text/html,application/xhtml+xml,*/*' },
      signal: AbortSignal.timeout(20000),
    });
    const body = method === 'GET' ? await res.text().catch(() => '') : '';
    return { ok: true, status: res.status, location: res.headers.get('location'), headers: res.headers, body, url: res.url };
  } catch (err) {
    return { ok: false, error: String(err?.cause?.code || err?.cause?.message || err?.message || err) };
  }
}

const abs = (loc, base) => new URL(loc, base).toString();
const strip = (u) => { try { const x = new URL(u); x.hash = ''; return x.href; } catch { return u; } };
const canonicalOf = (html) => (html.match(/<link[^>]+rel=["']canonical["'][^>]*>/i)?.[0].match(/href=["']([^"']+)/i) || [])[1] || null;
const titleOf = (html) => {
  const m = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  if (!m) return null;
  return m[1].replace(/\s+/g, ' ').trim()
    .replace(/&amp;/g, '&').replace(/&#39;|&apos;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
};
const beaconTokens = (html) =>
  [...new Set([...html.matchAll(/data-cf-beacon=[^>]*?token(?:"|&quot;|&#34;|&#x22;)\s*:\s*(?:"|&quot;|&#34;|&#x22;)([0-9a-f]{16,})/gi)].map((m) => m[1]))];
async function cfApi(path) {
  if (!CF_TOKEN || !CF_ACCOUNT) return null;
  try {
    const r = await fetch(`https://api.cloudflare.com/client/v4/accounts/${CF_ACCOUNT}${path}`, {
      headers: { authorization: `Bearer ${CF_TOKEN}` }, signal: AbortSignal.timeout(20000),
    }).then((x) => x.json());
    return r?.success ? r.result : null;
  } catch { return null; }
}
const noindex = (html, headers) =>
  /<meta[^>]+name=["']robots["'][^>]+content=["'][^"']*noindex/i.test(html) || /noindex/i.test(headers.get('x-robots-tag') || '');

// ── 1. One canonical origin ──────────────────────────────────────────────
const start = new URL(target);
const apex = start.hostname.replace(/^www\./, '');
const home = await req(`https://${start.hostname}/`, { follow: true });
if (!home.ok) {
  add('FAIL', 'origin', `https://${start.hostname}/ does not load: ${home.error}`, 'R1');
  finish();
}
if (/\.cloudflareaccess\.com$/.test(new URL(home.url).hostname)) {
  add('INFO', 'origin', `${target} is behind Cloudflare Access (private): nothing public to check`);
  finish();
}
const origin = new URL(home.url).origin;
const host = new URL(origin).hostname;
add('INFO', 'origin', `canonical origin is ${origin}`);

for (const variant of [`http://${apex}/`, `https://${apex}/`, `http://www.${apex}/`, `https://www.${apex}/`]) {
  if (new URL(variant).origin === origin) continue;
  const r = await req(variant);
  if (!r.ok) {
    // A www host that does not exist at all is fine; one that resets is not.
    const missing = /ENOTFOUND|EAI_AGAIN/.test(r.error);
    add(missing ? 'INFO' : 'FAIL', 'origin', `${variant} ${missing ? 'does not resolve (fine if never published)' : `fails: ${r.error}`}`, missing ? undefined : 'R1');
    continue;
  }
  if (r.status >= 300 && r.status < 400) {
    const to = abs(r.location, variant);
    const toOrigin = new URL(to).origin;
    if (![301, 308].includes(r.status)) add('FAIL', 'origin', `${variant} redirects with ${r.status}; needs 301/308`, 'R1');
    else if (toOrigin !== origin) {
      // Allow one extra hop only for http→https on the same host before the host move.
      const hop2 = await req(to);
      const final = hop2.ok && hop2.status >= 300 && hop2.status < 400 ? new URL(abs(hop2.location, to)).origin : toOrigin;
      // http→https on the same host first is Cloudflare's "Always Use HTTPS"; two short hops are harmless.
      const httpsFirst = new URL(variant).protocol === 'http:' && new URL(to).hostname === new URL(variant).hostname;
      if (final !== origin) add('FAIL', 'origin', `${variant} → ${to} → … never reaches ${origin}`, 'R1');
      else add(httpsFirst ? 'INFO' : 'WARN', 'origin', `${variant} → ${to} → ${origin} (two hops${httpsFirst ? ', https first: fine' : ''})`, httpsFirst ? undefined : 'R1');
    } else add('PASS', 'origin', `${variant} → ${r.status} ${to}`);
  } else if (r.status === 200) {
    const hit = /hit/i.test(r.headers.get('cf-cache-status') || '');
    if (new URL(variant).protocol === 'http:') add('FAIL', 'origin', `${variant} serves the site over plain http (200) instead of redirecting to https`, 'R1');
    else add('FAIL', 'origin', `${variant} serves the site itself (200)${hit ? ', as a cache hit: a cache shared across hostnames answers before the redirect' : ''}: a duplicate of ${origin}`, hit ? 'R5' : 'R1');
  } else add('WARN', 'origin', `${variant} answers ${r.status}`, 'R1');
}

// The canonical origin must not redirect to itself (a cached www→apex redirect served on the apex).
const self = await req(`${origin}/`);
if (self.ok && self.status >= 300 && self.status < 400 && new URL(abs(self.location, origin)).origin === origin && new URL(abs(self.location, origin)).pathname === '/') {
  add('FAIL', 'origin', `${origin}/ redirects to itself (${self.status}): a cached redirect`, 'R5');
}

// ── 1b. The platform's own address redirects too ────────────────────────
// Every Pages project answers on <project>.pages.dev and a Worker on
// <name>.<account>.workers.dev. Left serving the site, that is a second copy
// that splits analytics (keeporsellcalc, Oct 2026: a fifth of page loads)
// and can be indexed. Preview deployments (<hash>.<project>.pages.dev) are fine.
const platform = new Set(ALIASES);
// Pages lists 10 projects a page and rejects a larger per_page.
let projects = null;
for (let page = 1; page <= 20; page++) {
  const batch = await cfApi(`/pages/projects?page=${page}`);
  if (!batch) break;
  projects = [...(projects || []), ...batch];
  if (batch.length < 10) break;
}
const wdomains = await cfApi('/workers/domains');
const wsub = await cfApi('/workers/subdomain');
for (const p of projects || []) if ((p.domains || []).some((d) => d.replace(/^www\./, '') === apex)) platform.add(p.subdomain);
for (const d of wdomains || []) if (d.hostname.replace(/^www\./, '') === apex && wsub?.subdomain) platform.add(`${d.service}.${wsub.subdomain}.workers.dev`);
if (!projects && !ALIASES.length) add('INFO', 'platform', 'pages.dev / workers.dev address not checked: set CLOUDFLARE_API_TOKEN + CF_ACCOUNT_ID, or pass --alias');
for (const alias of platform) {
  const u = `https://${alias}/`;
  const r = await req(u);
  if (!r.ok) { add('INFO', 'platform', `${u} does not answer (${r.error})`); continue; }
  if ([301, 308].includes(r.status) && new URL(abs(r.location, u)).origin === origin) add('PASS', 'platform', `${u} → ${r.status} ${origin}`);
  else if (r.status >= 300 && r.status < 400) add('FAIL', 'platform', `${u} redirects with ${r.status} to ${r.location}; needs 301/308 to ${origin}`, 'R9');
  else if (r.status === 200) {
    const c = canonicalOf(r.body);
    const canonOk = c && new URL(abs(c, u)).origin === origin;
    add(canonOk ? 'WARN' : 'FAIL', 'platform', `${u} serves the site itself (200)${canonOk ? ` with canonical → ${origin}: not indexed, but its visits are counted under another host` : `: a duplicate of ${origin}`}`, 'R9');
  } else if ([401, 403, 404].includes(r.status) || /\.cloudflareaccess\.com$/.test(r.location || '')) add('PASS', 'platform', `${u} answers ${r.status} (not serving the site)`);
  else add('WARN', 'platform', `${u} answers ${r.status}`, 'R9');
}

// ── 2. Unknown pages are real 404s ───────────────────────────────────────
const probe = `${origin}/launch-check-${Math.random().toString(36).slice(2, 10)}`;
const nf = await req(probe);
if (!nf.ok) add('WARN', '404', `could not fetch ${probe}: ${nf.error}`);
else if (nf.status === 404 || nf.status === 410) add('PASS', '404', `unknown path answers ${nf.status}`);
else if (nf.status === 200) add('FAIL', '404', `unknown path answers 200 (soft-404): ${probe}`, 'R2');
else if (nf.status >= 300 && nf.status < 400) add('FAIL', '404', `unknown path redirects (${nf.status} → ${nf.location}) instead of 404`, 'R2');
else add('WARN', '404', `unknown path answers ${nf.status}`, 'R2');

// ── 3. robots.txt and the sitemap ────────────────────────────────────────
const robots = await req(`${origin}/robots.txt`);
let sitemapUrls = [];
if (!robots.ok || robots.status !== 200) add('WARN', 'robots', `robots.txt answers ${robots.status ?? robots.error}`, 'R3');
else {
  if (starGroupBlocksAll(robots.body)) add('FAIL', 'robots', 'robots.txt disallows everything for User-agent: *', 'R3');
  sitemapUrls = [...robots.body.matchAll(/^\s*sitemap:\s*(\S+)/gim)].map((m) => m[1]);
  if (!sitemapUrls.length) add('WARN', 'robots', 'robots.txt names no Sitemap', 'R3');
}
if (!sitemapUrls.length) sitemapUrls = [`${origin}/sitemap.xml`, `${origin}/sitemap-index.xml`];

const pages = [];
const seen = new Set();
async function readSitemap(url, depth = 0) {
  if (seen.has(url) || depth > 2 || pages.length >= 5000) return;
  seen.add(url);
  const r = await req(url, { follow: true });
  if (!r.ok || r.status !== 200 || !/<(urlset|sitemapindex)/i.test(r.body)) return;
  if (new URL(url).origin !== origin) add('FAIL', 'sitemap', `sitemap ${url} is not on ${origin}`, 'R3');
  const locs = [...r.body.matchAll(/<loc>\s*([^<\s]+)\s*<\/loc>/gi)].map((m) => m[1].replace(/&amp;/g, '&'));
  if (/<sitemapindex/i.test(r.body)) for (const l of locs) await readSitemap(l, depth + 1);
  else pages.push(...locs);
}
for (const s of sitemapUrls) await readSitemap(s);
if (!pages.length) add('FAIL', 'sitemap', `no sitemap found (${sitemapUrls.join(', ')})`, 'R3');
else {
  add('INFO', 'sitemap', `${pages.length} URLs in the sitemap`);
  const off = pages.filter((p) => { try { return new URL(p).origin !== origin; } catch { return true; } });
  if (off.length) add('FAIL', 'sitemap', `${off.length} sitemap URLs are not on ${origin}, e.g. ${off[0]}`, 'R3');
}

// ── 4. Sampled pages: 200, self-canonical, indexable, titled ─────────────
const sample = [...new Set([`${origin}/`, ...spread(pages, PAGES)])];
const bad = { status: [], canon: [], noidx: [], title: [], head: [], beacon: [], beaconMix: [] };
const homeTokens = beaconTokens(home.body);
for (const u of sample) {
  const r = await req(u);
  if (!r.ok) { bad.status.push(`${u} (${r.error})`); continue; }
  if (r.status !== 200) { bad.status.push(`${u} → ${r.status}${r.location ? ' ' + r.location : ''}`); continue; }
  const c = canonicalOf(r.body);
  if (!c) bad.canon.push(`${u} has no canonical tag`);
  else if (strip(abs(c, u)) !== strip(u)) bad.canon.push(`${u} → canonical ${abs(c, u)}`);
  if (noindex(r.body, r.headers)) bad.noidx.push(u);
  const t = titleOf(r.body);
  if (!t) bad.title.push(`${u} has no <title>`);
  else if (t.length > TITLE_MAX) bad.title.push(`${u} (${t.length} chars): ${t}`);
  if (homeTokens.length) {
    const tk = beaconTokens(r.body);
    if (!tk.length) bad.beacon.push(u);
    else if (tk.some((t) => !homeTokens.includes(t))) bad.beaconMix.push(`${u} (token ${tk.map((t) => t.slice(0, 6)).join(', ')})`);
  }
  const h = await req(u, { method: 'HEAD' });
  if (h.ok && h.status !== r.status) bad.head.push(`${u}: HEAD ${h.status}, GET ${r.status}`);
}
report('pages', bad.status, `sampled sitemap URLs answer 200 directly (${sample.length} checked)`, 'FAIL', 'R3', 'answer something other than a direct 200');
report('canonical', bad.canon, 'every sampled page is canonical to itself', 'FAIL', 'R3', 'are not canonical to themselves');
report('noindex', bad.noidx, 'no sampled page is noindex', 'FAIL', 'R3', 'are in the sitemap but noindex');
report('head', bad.head, 'HEAD matches GET on every sampled page', 'FAIL', 'R4', 'answer HEAD differently from GET');
if (homeTokens.length) {
  report('beacon', bad.beacon, 'every sampled page carries the analytics beacon', 'WARN', 'R8', 'carry no analytics beacon (pages rendered by Functions or a server get no Pages injection)');
  report('beacon', bad.beaconMix, 'every sampled page reports to the same analytics site as the home page', 'FAIL', 'R8', 'report to a different analytics site than the home page');
}
report('title', bad.title, `every sampled title is ≤ ${TITLE_MAX} characters`, 'WARN', 'R7', 'have a missing or long title');

// ── 5. URL variants of a real page redirect permanently ──────────────────
const pagePath = pages.map((p) => { try { return new URL(p); } catch { return null; } })
  .find((p) => p && p.origin === origin && p.pathname.length > 1);
if (pagePath) {
  const clean = strip(pagePath.toString());
  const base = clean.replace(/\/$/, '').replace(/\.html$/, '');
  const variants = new Set([`${base}.html`, `${base}/`, base].filter((v) => v !== clean));
  for (const v of variants) {
    const r = await req(v);
    if (!r.ok) continue;
    if (r.status >= 300 && r.status < 400) {
      const to = strip(abs(r.location, v));
      if (![301, 308].includes(r.status)) add('FAIL', 'variants', `${v} redirects with ${r.status} (temporary); needs 301/308`, 'R6');
      else if (to !== clean) add('WARN', 'variants', `${v} → ${to}, not the sitemap URL ${clean}`, 'R6');
      else add('PASS', 'variants', `${v} → ${r.status} ${to}`);
    } else if (r.status === 200) {
      const c = canonicalOf(r.body);
      if (c && strip(abs(c, v)) === clean) add('WARN', 'variants', `${v} serves a duplicate (200) with canonical → ${clean}; a 301 is cleaner`, 'R6');
      else add('FAIL', 'variants', `${v} serves a duplicate (200) of ${clean}`, 'R6');
    }
  }
}

// ── 6. Analytics: exactly one Cloudflare beacon ──────────────────────────
const tokens = homeTokens;
if (!tokens.length) add('WARN', 'analytics', 'no Cloudflare Web Analytics beacon on the home page', 'R8');
else if (tokens.length > 1) add('FAIL', 'analytics', `${tokens.length} different beacon tokens on the home page (${tokens.map((t) => t.slice(0, 6)).join(', ')}): one is stale`, 'R8');
else add('PASS', 'analytics', `one beacon (token ${tokens[0].slice(0, 6)}…)`);

// One Web Analytics site per domain. A Pages project's snippet site and the
// zone's automatic site can both exist for one domain; each counts a different
// set of pages and the Cloudflare dashboard shows two half-pictures
// (buildpermitguide, keeporsellcalc, howlifecompares, Oct 2026).
const rumSites = await cfApi('/rum/site_info/list?per_page=100');
if (rumSites) {
  const covers = (site) => {
    if (site.host) { try { return new RegExp(site.host).test(host); } catch { return site.host.includes(host); } }
    return site.ruleset?.zone_name && (host === site.ruleset.zone_name || host.endsWith(`.${site.ruleset.zone_name}`));
  };
  const active = rumSites.filter((x) => covers(x) && (x.auto_install ? x.ruleset?.enabled !== false : true));
  const label = (x) => `${x.host ? 'JS snippet' : 'automatic'} site ${x.site_tag.slice(0, 6)}… (token ${x.site_token.slice(0, 6)}…)`;
  const onPage = active.filter((x) => tokens.includes(x.site_token));
  if (tokens.length && !rumSites.some((x) => tokens.includes(x.site_token))) add('FAIL', 'analytics', `the beacon token ${tokens[0].slice(0, 6)}… belongs to no Web Analytics site on this account: it records nowhere you can see`, 'R8');
  if (active.length > 1) {
    const keep = onPage[0] || active[0];
    add('WARN', 'analytics', `${active.length} active Web Analytics sites cover ${host}: ${active.map(label).join(', ')}. Keep the ${label(keep)}${onPage.length ? ' whose token is on the page' : ''}; disable the others once every page carries its beacon`, 'R10');
  } else if (active.length === 1) add('PASS', 'analytics', `one Web Analytics site covers ${host}`);
} else if (CF_TOKEN && CF_ACCOUNT) add('INFO', 'analytics', 'could not list Web Analytics sites (the token needs Account · Account Analytics · Read and Web Analytics read)');

// Optional: does Cloudflare actually have page loads for this host? Needs the read-only analytics token.
if (tokens.length && process.env.CLOUDFLARE_ANALYTICS_TOKEN && (process.env.CF_ACCOUNT_ID || process.env.CLOUDFLARE_ACCOUNT_ID)) {
  const to = new Date(Date.now() - 864e5).toISOString().slice(0, 10);
  const from = new Date(Date.now() - 14 * 864e5).toISOString().slice(0, 10);
  const query = `query($a:string!,$f:Date!,$t:Date!,$h:string!){viewer{accounts(filter:{accountTag:$a}){rum:rumPageloadEventsAdaptiveGroups(limit:1,filter:{date_geq:$f,date_leq:$t,requestHost:$h}){count}}}}`;
  try {
    const r = await fetch('https://api.cloudflare.com/client/v4/graphql', {
      method: 'POST',
      headers: { authorization: `Bearer ${process.env.CLOUDFLARE_ANALYTICS_TOKEN}`, 'content-type': 'application/json' },
      body: JSON.stringify({ query, variables: { a: process.env.CF_ACCOUNT_ID || process.env.CLOUDFLARE_ACCOUNT_ID, f: from, t: to, h: host } }),
    }).then((x) => x.json());
    const n = r?.data?.viewer?.accounts?.[0]?.rum?.[0]?.count ?? 0;
    if (n > 0) add('PASS', 'analytics', `Web Analytics has page loads for ${host} in the last 14 days`);
    else add('WARN', 'analytics', `Web Analytics has no page loads for ${host} in 14 days: the beacon may belong to another site (or the site is new)`, 'R8');
  } catch { /* optional check; say nothing */ }
}

finish();

// ── helpers ──────────────────────────────────────────────────────────────
function starGroupBlocksAll(txt) {
  // Groups are runs of User-agent lines followed by rules; only `*` speaks for search engines at large.
  let inStar = false, lastWasAgent = false, blocks = false, allows = false;
  for (const raw of txt.split(/\r?\n/)) {
    const line = raw.replace(/#.*/, '').trim();
    if (!line) continue;
    const [k, ...rest] = line.split(':');
    const key = k.trim().toLowerCase(), val = rest.join(':').trim();
    if (key === 'user-agent') { if (!lastWasAgent) inStar = false; if (val === '*') inStar = true; lastWasAgent = true; continue; }
    lastWasAgent = false;
    if (!inStar) continue;
    if (key === 'disallow' && val === '/') blocks = true;
    if (key === 'allow' && val && val !== '') allows = true;
  }
  return blocks && !allows;
}
function spread(list, n) {
  if (list.length <= n) return list;
  const step = list.length / n;
  return Array.from({ length: n }, (_, i) => list[Math.floor(i * step)]);
}
function report(id, items, okMsg, level, recipe, badMsg) {
  if (!items.length) return add('PASS', id, okMsg);
  add(level, id, `${items.length} ${badMsg}: ${items.slice(0, 3).join(' · ')}${items.length > 3 ? ' …' : ''}`, recipe);
}
function finish() {
  const fails = results.filter((r) => r.level === 'FAIL').length;
  if (JSON_OUT) console.log(JSON.stringify({ target, results, fails }, null, 2));
  else {
    console.log(`launch-check ${target}\n`);
    for (const r of results) console.log(`${r.level.padEnd(4)}  ${r.id.padEnd(9)} ${r.msg}${r.recipe ? `  [${r.recipe}]` : ''}`);
    const warns = results.filter((r) => r.level === 'WARN').length;
    console.log(`\n${fails} fail, ${warns} warn`);
  }
  process.exit(fails ? 1 : 0);
}
