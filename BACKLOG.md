# Backlog — Comeback Towns

The task list for this repo. Sessions read it at the start and keep it current (see CLAUDE.md → "Owner & backlog").
Model tag = suggested model for the job. Source: portfolio triage of 21 Oct 2026.

## Ready (an agent can do these)


## Ready (found 2026-10-24)


## Needs Emory (money, access, limits, messages in their name — each with the exact step)

- [ ] Request indexing on the pages Google still holds under the old canonical: in Search Console (property sc-domain:comebacktowns.com) → URL inspection, paste each clean URL, "Request indexing". The list is the "Alternate page with proper canonical tag" group in the dashboard's Index coverage drawer for comebacktowns (23 on 2026-11-08) plus /town/coxsackie-ny ("URL is unknown to Google"). Only the property owner's account can do this; the API has no request-indexing call. It speeds up what Google is already doing on its own (27 → 23 between 6 and 8 Nov).

## Waiting (time-bound)

- [ ] Expand beyond New York when ruling R5's gate is met: ≥ 300 Google clicks on NY town pages in a 28-day window (3 on 2026-11-07) and two consecutive clean monthly refreshes. Measured, not decided.
- [ ] Confirm the 2 Dec 2026 OSM Workflow instance stored files and which mirror answered  _(R2 listing or Workflow logs; the Nov 2, 3 and 6 instances all errored on the mirrors, see Ready, and the GitHub ingest filled all 148)_
- [ ] Verify `wrangler workflows instances describe` output matches the wait step's `status` parse on the first real run (a manual osm-workflow dispatch after merge is enough)
- [ ] Re-read Search Console for /county/* and /region/* about 4 weeks after the title change ships (baseline: Westchester pos 10.4, Mohawk Valley pos 11.3)

## Done

- [x] 2026-11-11 Operating policy adopted and audited (CLAUDE.md "Operating policy", `docs/DECISIONS.md`): no model is called by deployed code (the secrets are Cloudflare's, the Census key and the dashboard's reporting token; none is a model key); six rulings replace the owner-waits in CLAUDE.md, seed/README.md and the watchdog; `refresh-watchdog.yml` now retries the refresh itself on the 3rd, 5th and 9th and a publish closes the month's failure issues; "Needs Emory" holds only the Search Console request-indexing step. A scheduled Claude session ("Comeback Towns monthly session", the 4th and 10th at 12:17 UTC, fresh session each time) applies the rulings each month: refresh state, R2 drift, OSM Workflow, site health, numbers against the R5 gate, PR under R1. PR #50.
- [x] 2026-11-11 Web Analytics confirmed recording real visits since the first-party beacon (Cloudflare: 8, 6, 1, 5 and 2 page views on 6–11 Nov; dashboard visits tile moving).
- [x] 2026-11-08 Dashboard "not indexed" counts pages, not views of pages (AI-project-dashboard PR #41): comebacktowns 196 → 34, with 10 "moved" shown separately; 148 /compare?towns= links no longer inspected.
- [x] 2026-11-06 Web Analytics recorded nothing from 6 Oct to 6 Nov: the beacon posted to cloudflareinsights.com and was refused (CORS, hostname not registered on the automatic-setup site record). It now posts first-party to the site's own /cdn-cgi/rum, which the zone accepts; verified in headless Chromium (HTTP 204) and in Cloudflare's analytics (events recorded against the site tag). Details in `docs/DECISIONS.md`. PR #49.
- [x] 2026-11-06 OSM Workflow mirrors: probed eleven public Overpass servers from a throwaway Worker; none reachable from Cloudflare's edge serves a current global map (details in `docs/DECISIONS.md`). The Workflow now probes its servers first and completes with "no usable server" in seconds when none qualifies, so refresh-monthly loses no time and the head start returns on its own when a mirror recovers. PR #48.
- [x] 2026-11-06 November data published (refresh-monthly run 42269967641): all 148 towns fetched fresh from overpass-api.de over two resumed runs, QA rule 4 passed, site shows readiness and momentum computed 2026-11-06. Issues #41, #42, #45 closed.
- [x] 2026-11-06 Saugerties re-baselined in `seed/pilot_v0.csv` (49.9 → 53.8, PR #46): the +3.9 drift reproduced on fresh Nov 2 and Nov 6 snapshots; its OpenStreetMap business elements went 49 → 67 (18 mapped in October), a genuine input change. Decision in `docs/DECISIONS.md`; the fixture README names this case.
- [x] 2026-11-06 PR #43 (orchestrator on Workers Paid + Container) closed unmerged, Emory's decision: Overpass is not reachable from Cloudflare's network, #40 already mitigates dropped cron slots, and the branch was never built or run. Revisit only if both 2 Dec slots are dropped; keep the Overpass fetch on a GitHub runner in any new shape.
- [x] 2026-11-05 Web Analytics automatic setup switched off for comebacktowns.com (Emory, dashboard); the page beacon is the only reporter now.
- [x] 2026-11-02 Monthly refresh no longer depends on silent schedulers: removed the ignored Workflows `schedules` key, refresh-monthly starts and waits for the OSM Workflow, second cron slot with guard, `refresh-watchdog.yml` on the 3rd. Next `wrangler deploy` drops the key from config (harmless until then). PR #40.

- [x] 2026-10-25 Home page title shortened from 65 to 51 characters (launch-check R7), PR pending. launch-check on the live site otherwise passes: 0 fail. Still open: R8 reports no Web Analytics page loads in 14 days (see Needs Emory).
- [x] 2026-10-25 /sources stays indexed (decision, no code change). It is the provenance page every town page, the footer and llms.txt point to, and it lists the real source URLs, including the Zillow CSV links people search for. Its 0-click impressions cost nothing: they only drag the site-wide CTR figure down, and noindex would remove the page that backs the site's claims. Revisit only if Search Console shows it displacing a page that should rank.
- [x] 2026-10-25 Town pages: H1 now "Name, NY" (matches "port jervis ny"-style queries) and an "Other places in X County" link block on every town page (PR #36). The "what is X" lead already exists as the first summary sentence. Rankings of 30-80 mostly reflect a five-week-old domain, so expect little movement; re-read Search Console around 21 Nov with the county/region titles.
- [x] 2026-10-24 Titles/descriptions rewritten for county and region pages (PR #35). Search Console shows ~1,600 of the site's impressions are one Zillow CSV filename landing on /sources (pos 6, 0 clicks, not an audience worth chasing); town pages rank 30-80 for bare names, which a title cannot fix.
- [x] 2026-10-24 OSM check (PR #35): 2026-10-05 monthly run stored 148 of 148 files, all from overpass-api.de (504/429 retries, no fallback needed). The Workflow's own mirror use is not visible from GitHub.
