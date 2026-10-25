# Backlog — Comeback Towns

The task list for this repo. Sessions read it at the start and keep it current (see CLAUDE.md → "Owner & backlog").
Model tag = suggested model for the job. Source: portfolio triage of 21 Oct 2026.

## Ready (an agent can do these)


## Ready (found 2026-10-24)


## Needs Emory (decisions, accounts, money, Search Console, outreach)

- [ ] Check Cloudflare Web Analytics for comebacktowns.com: launch-check (2026-10-25) says no page loads in 14 days although every page carries the beacon (token 27ba39…). Confirm the token belongs to this site's Web Analytics entry  _(Cloudflare dashboard)_
- [ ] Request indexing on key pages as alternate canonicals fall  _(Search Console session)_
- [ ] Expand beyond NY? (once NY pages earn traffic)  _(Decisions)_

## Waiting (time-bound)

- [ ] Confirm the first scheduled OSM Workflow run (2 Nov 2026, 03:00 UTC) stored 148 files and which mirror answered  _(needs R2 listing or Workflow logs; the GitHub trigger job only starts the instance)_
- [ ] Re-read Search Console for /county/* and /region/* about 4 weeks after the title change ships (baseline: Westchester pos 10.4, Mohawk Valley pos 11.3)

## Done

- [x] 2026-10-25 Home page title shortened from 65 to 51 characters (launch-check R7), PR pending. launch-check on the live site otherwise passes: 0 fail. Still open: R8 reports no Web Analytics page loads in 14 days (see Needs Emory).
- [x] 2026-10-25 /sources stays indexed (decision, no code change). It is the provenance page every town page, the footer and llms.txt point to, and it lists the real source URLs, including the Zillow CSV links people search for. Its 0-click impressions cost nothing: they only drag the site-wide CTR figure down, and noindex would remove the page that backs the site's claims. Revisit only if Search Console shows it displacing a page that should rank.
- [x] 2026-10-25 Town pages: H1 now "Name, NY" (matches "port jervis ny"-style queries) and an "Other places in X County" link block on every town page (PR #36). The "what is X" lead already exists as the first summary sentence. Rankings of 30-80 mostly reflect a five-week-old domain, so expect little movement; re-read Search Console around 21 Nov with the county/region titles.
- [x] 2026-10-24 Titles/descriptions rewritten for county and region pages (PR #35). Search Console shows ~1,600 of the site's impressions are one Zillow CSV filename landing on /sources (pos 6, 0 clicks, not an audience worth chasing); town pages rank 30-80 for bare names, which a title cannot fix.
- [x] 2026-10-24 OSM check (PR #35): 2026-10-05 monthly run stored 148 of 148 files, all from overpass-api.de (504/429 retries, no fallback needed). The Workflow's own mirror use is not visible from GitHub.
