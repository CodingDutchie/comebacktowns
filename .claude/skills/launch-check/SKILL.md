---
name: launch-check
description: Probe a live website for the indexing and analytics mistakes that kept recurring across Emory's portfolio — duplicate hosts (www, http, bare domain, the pages.dev / workers.dev address), soft-404s, canonical/sitemap mismatches, HEAD returning 404, temporary or cached redirects, long titles, missing or stale Cloudflare Web Analytics beacons, pages without the beacon, duplicate Web Analytics sites for one domain — and fix them with tested recipes. Use before a site's first launch, after any domain, DNS, hosting or routing change, when Search Console shows "Alternate page", "Duplicate", "Soft 404" or "Page with redirect" exclusions, or when the user asks to check a site's SEO/indexing setup.
---

# launch-check

Every one of these was found in production in October 2026, on sites that looked
fine in a browser. They are launch-time decisions made by platform defaults that
nobody revisits, they cost weeks of indexing before Search Console shows them, and
all of them can be tested with plain HTTP. So test them, before Google does.

## Run it

```bash
node .claude/skills/launch-check/check.mjs https://example.com
node .claude/skills/launch-check/check.mjs https://example.com --pages 60   # sample more sitemap URLs
node .claude/skills/launch-check/check.mjs https://example.com --json       # for CI
node .claude/skills/launch-check/check.mjs https://example.com --alias foo.pages.dev  # extra host to test
```

No dependencies, Node 18+. Exit code 1 on any FAIL, so it can gate a deploy
smoke-check. With `CLOUDFLARE_ANALYTICS_TOKEN` and `CF_ACCOUNT_ID` (or
`CLOUDFLARE_ACCOUNT_ID`) in the environment it also asks Cloudflare whether the
beacon is actually recording this host. With `CLOUDFLARE_API_TOKEN` (Pages and
Workers read, Web Analytics read) and the account id it also finds the site's own
`*.pages.dev` / `*.workers.dev` address and its Web Analytics sites by itself;
without it, pass `--alias` for the platform address.

**When:** before the first public launch; after every domain, DNS, hosting,
redirect or routing change; after adding analytics; and whenever Search Console's
Page indexing report shows a reason other than "Crawled/Discovered – currently not
indexed".

## Reading the output

`FAIL` is a real duplicate, soft-404 or mismatch Google will act on: fix before
launch. `WARN` is worth fixing but not urgent. `INFO` is context. Each line names
its recipe below.

What it checks:

| Check | Passes when |
|---|---|
| origin | every host/scheme variant (http/https × bare/www) 301/308s to one canonical origin; the origin never redirects to itself |
| 404 | a random path answers 404, not 200 or a redirect |
| robots / sitemap | robots.txt names a sitemap, `User-agent: *` is not blocked, every sitemap URL is on the canonical origin |
| pages | sampled sitemap URLs answer 200 directly, are canonical to themselves, are not noindex |
| head | HEAD returns the same status as GET |
| variants | `.html` and trailing-slash twins of a real page 301/308 to it |
| platform | the project's `*.pages.dev` / `*.workers.dev` address 301s to the canonical origin (or does not serve the site) |
| title | ≤ 60 characters (WARN only) |
| beacon | every sampled page carries the beacon, and the same token as the home page |
| analytics | exactly one Cloudflare beacon; with the tokens, it belongs to a site on the account, only one active Web Analytics site covers the host, and Cloudflare has page loads for it |

Do not act on a result you have not reproduced with `curl -sSI`. And do not tell
the user something is fixed until a re-run of this script against the live site
says so — "deployed" is not "verified".

## Recipes

### R1 — One canonical origin

Pick one origin (usually `https://` + bare domain) and send every other host and
scheme there with a **301** in **one hop**, path and query kept.

**Cloudflare Pages** — `_redirects` cannot match on host; use middleware
(`functions/_middleware.js`):

```js
const WWW_HOST = 'www.example.com';
const APEX_ORIGIN = 'https://example.com';
export async function onRequest({ request, next }) {
  const url = new URL(request.url);
  if (url.hostname === WWW_HOST) return Response.redirect(`${APEX_ORIGIN}${url.pathname}${url.search}`, 301);
  return next();
}
```

Deploy with `wrangler pages deploy` **from the repo root** — wrangler compiles
`./functions` from the working directory, not from the output folder, and
silently drops it otherwise.

**Worker** — first lines of `fetch`, before anything else:

```js
const url = new URL(request.url);
if (url.protocol === 'http:' || url.hostname.startsWith('www.')) {
  url.protocol = 'https:';
  url.hostname = url.hostname.replace(/^www\./, '');
  return new Response(null, { status: 301, headers: { location: url.toString(), 'cache-control': 'no-store' } });
}
```

(Or turn on SSL/TLS → Edge Certificates → **Always Use HTTPS** for the zone; the
Worker line works without zone access.)

**Bare domain on a registrar's DNS** (Namecheap URL redirect and the like): those
redirect services have no TLS, so `https://example.com` resets the connection.
Move the zone's DNS to Cloudflare, add the bare domain as a Pages/Workers custom
domain, and redirect it. Copy every mail record exactly, keep `autodiscover`
**DNS only** (proxied breaks Outlook setup), and never enable Email Routing on a
domain whose mail is Microsoft 365 or Google.

### R2 — Unknown URLs are real 404s

- **Pages:** ship a `404.html`. Without it Pages treats the site as an SPA and
  answers every unknown path with `index.html` and a 200. Delete any
  `/* /index.html 200` line in `_redirects` unless the site truly is a client-side
  router, and then prerender its routes instead.
- **Workers static assets:** `not_found_handling = "404-page"` in `[assets]`.
- Give the 404 page `<meta name="robots" content="noindex">` and a link home.

### R3 — Canonical, sitemap and served URL agree

One URL form everywhere: the canonical tag, the sitemap `<loc>`, internal links and
the URL the server answers 200 on must be byte-identical — same host, same
scheme, same trailing-slash and extension policy. Decide it once in the framework
config (Astro: `trailingSlash` + `build.format`; Next: `trailingSlash`) and
generate canonicals and the sitemap from the same function. The sitemap lists
only 200, indexable, self-canonical URLs. robots.txt carries
`Sitemap: https://<origin>/sitemap…xml` and does not block `User-agent: *`.

### R4 — HEAD answers like GET

Pages Functions route by method: a file exporting only `onRequestGet` answers HEAD
with 404, and uptime monitors, link checkers and some crawlers send HEAD.

```js
// shared helper
export const headFromGet = (get) => async (ctx) => {
  const res = await get(ctx);
  return new Response(null, { status: res.status, headers: res.headers });
};
// in each route file
export const onRequestHead = headFromGet(onRequestGet);
```

A rewrite of HEAD to GET in `_middleware.js` does **not** work — routing has
already been decided by method. Hono and plain Workers handle HEAD for you.

### R5 — Redirects are never cached; caches never cross hosts

- Put `Cache-Control: no-store` on every redirect a Worker returns. A cached
  www→apex 301 for `/` was served back on the apex itself: the homepage redirected
  to itself for every visitor, Googlebot included.
- **Workers Caching (`[cache] enabled = true`) shares one cache across every
  hostname bound to the Worker — the key has no host.** A page cached from the
  apex is served on `www.` as a HIT and the Worker's redirect never runs. Fix with
  the documented gateway pattern: caching off on the default entrypoint, which
  does the host/scheme redirects and forwards the rest to a cached named
  entrypoint:

```toml
[cache]
enabled = true
[exports.default]
type = "worker"
  [exports.default.cache]
  enabled = false
[exports.Site]
type = "worker"
  [exports.Site.cache]
  enabled = true
```

```js
import { WorkerEntrypoint } from 'cloudflare:workers';
export class Site extends WorkerEntrypoint { fetch(req) { return app.fetch(req, this.env, this.ctx); } }
export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    if (url.hostname !== 'example.com' || url.protocol !== 'https:') { /* R1 redirect, no-store */ }
    return ctx.exports.Site.fetch(req);
  },
};
```

Purge the cache after deploying the change.

### R6 — Old URL forms redirect permanently

`/page.html` and `/page/` must **301/308** to `/page` (or whichever form R3 chose).
Workers static assets normalise these themselves but answer **307 Temporary** —
which tells Google to keep the old URL as canonical (69 pages of "Alternate page
with proper canonical tag" on one site). With `run_worker_first`, upgrade them:

```ts
const res = await env.ASSETS.fetch(request);
if (res.status === 307 && res.headers.get('location')) {
  const to = new URL(res.headers.get('location')!, request.url);
  if (to.origin === new URL(request.url).origin) return Response.redirect(to.toString(), 301);
}
return res;
```

A twin that serves 200 with a canonical to the clean URL works, but a 301 settles
it faster.

### R7 — Titles

≤ 60 characters, unique per page, most specific words first, site name short or
last. Generate them from data with a length check rather than writing them by hand.

### R8 — Analytics that actually count

- **Exactly one** Cloudflare Web Analytics beacon per page. When a site is
  (re)added to Web Analytics, delete any old hard-coded `beacon.min.js` tag —
  a stale token records to a site that is not this one, and the dashboard reads
  nothing.
- Zone **automatic injection does not reach pages a Worker serves**; put the
  beacon in the layout with the site's token (public by design).
- **Pages injects its beacon into static files only.** Pages rendered by Pages
  Functions (or any server-side route) get none, so with a Pages-injected beacon
  add the same `<script defer src='https://static.cloudflareinsights.com/beacon.min.js'
  data-cf-beacon='{"token": "…"}'></script>` to the HTML your Functions render, with
  the same token (buildpermitguide's change logs, Oct 2026). The `beacon` check
  samples sitemap pages; list Functions pages in a sitemap so it sees them.
- Verify the next day: Cloudflare must have page loads for the host (this script
  checks it with the analytics token). The portfolio dashboard collector reads
  the same data.

### R9 — The platform address is not a second site

Every Pages project also answers on `<project>.pages.dev`, and a Worker on
`<name>.<account>.workers.dev`. Serving the site there splits the analytics (one
site lost a fifth of its counted page loads to it) and leaves a duplicate for
crawlers. Redirect the production address, leave preview deployments alone:

```js
// functions/_middleware.js (Pages) — deploy from the repo root (see R1)
const PAGES_DEV_HOST = 'project.pages.dev';
const ORIGIN = 'https://example.com';
export async function onRequest({ request, next }) {
  const url = new URL(request.url);
  if (url.hostname === PAGES_DEV_HOST) {
    return new Response(null, { status: 301, headers: { location: `${ORIGIN}${url.pathname}${url.search}`, 'cache-control': 'no-store' } });
  }
  return next();
}
```

A Worker: include the workers.dev host in R1's redirect, or set
`workers_dev = false` in `wrangler.toml` so the address stops answering at all.
A 200 with a canonical to the real origin is only a WARN: Google will not index
it, but its visits are still counted under another host.

### R10 — One Web Analytics site per domain

A domain can end up with two Web Analytics sites: the Pages project's
**JS snippet** site (Pages → project → Metrics → Web Analytics) and the zone's
**automatic setup** site (Analytics & Logs → Web Analytics). Each counts a
different set of pages, so the Cloudflare dashboard shows two half-pictures.
Keep the one whose token is in the page HTML and that holds the history:

- **Static site on Pages**: keep the JS snippet site; disable automatic setup on
  the zone's site (Manage site). Add the snippet to any Functions-rendered pages
  first (R8), or they go untracked.
- **Site rendered by Pages Functions or a Worker**: keep the automatic site, it
  reaches every page; disable Web Analytics in the Pages project's Metrics tab.

Change it in this order: every page carries the kept beacon, then disable the
other. Never delete the Pages project or the Worker — only the analytics site.

## After fixing

1. Re-run this script against the live site; it must show 0 FAIL.
2. In Search Console: resubmit the sitemap, and "Request indexing" on a few key
   pages. Expect days to weeks before the Page indexing report moves.
3. Report it with the `portfolio-report` skill.
