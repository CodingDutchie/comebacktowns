---
name: portfolio-report
description: Report what a working session actually shipped to the portfolio dashboard, and register a project that is not on it yet. Use at the end of a session that made commits in one of Eddy's project repos, when the Stop hook asks for a report, or when the user says to report/log the session to the dashboard. Do not use for repos that are not part of the portfolio.
---

# Reporting a session to the portfolio dashboard

The dashboard measures everything it can on its own — commits, uptime, search
traffic — on a six-hourly cron. It cannot measure the one thing only this session
knows: **what actually shipped, and what is next.** That is what this skill sends.

Endpoint: `https://portfolio-dash.edekoop.workers.dev`

## Before anything

Check the credentials exist:

```bash
[ -n "$INGEST_TOKEN" ] && [ -n "$CF_ACCESS_CLIENT_ID" ] && [ -n "$CF_ACCESS_CLIENT_SECRET" ] || echo missing
```

**If any is missing, stop and say nothing further about it.** A session that
cannot report should skip silently rather than fail — the dashboard is not this
project's problem. Write the marker (see below) so the hook stops asking.

## What to send

```bash
curl -fsS -X POST "https://portfolio-dash.edekoop.workers.dev/api/ingest" \
  -H "Authorization: Bearer $INGEST_TOKEN" \
  -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET" \
  -H "content-type: application/json" \
  -d '{"slug":"<slug>",
       "completed":["what actually landed","and this"],
       "next":"the single next thing",
       "note":"one or two sentences of context"}'
```

The slug is the project's registry slug, which is usually — but not always — the
repo name lowercased. Guess it, and let the endpoint correct you: it always
returns HTTP 200, and an unknown slug comes back as

```json
{"ok":true,"applied":[],"ignored":[{"slug":"x","reason":"unknown slug — add it to projects.json first"}]}
```

**Check `applied` is non-empty.** A 200 with an empty `applied` array means
nothing was recorded. If the reason is an unknown slug, either the guess is wrong
or the project is not registered — go to *Registering a new project*.

## The four rules

1. **Outcomes, not intentions.** "Shipped the county pages" — not "worked on the
   county pages", and never "will add tests". If nothing shipped, send only a
   `note`, or send nothing at all. An empty session is a fine thing to not report.
2. **Never send a stage.** `stage` is deliberately not accepted. A model that just
   spent two hours on a project is the worst-placed observer of whether it is
   growing, and the dashboard infers stage from commits, traffic and uptime.
3. **`next` is one thing.** It becomes the "what's next" line on the board and
   promotes any previous `next` back to backlog. A list is a backlog, not a next.
4. **Numbers need provenance.** Metrics are only for figures with no API —
   Etsy revenue, app installs. Allowed keys: `revenue_mtd`, `units_mtd`,
   `installs`, `crash_free_pct`, `published_count`, `active_subs`,
   `sessions_28d`, `followers`. Every one needs `evidence` naming where it came
   from, or it is rejected:

```json
"metrics": { "revenue_mtd": { "value": 312.40, "unit": "usd", "period": "mtd",
             "observed_at": "2026-08-21",
             "evidence": "screenshot: Etsy Stats, 21 Aug 2026" } }
```

## After a successful report

Record the commit you reported, so the Stop hook does not ask again:

```bash
git rev-parse HEAD > "$(git rev-parse --git-dir)/portfolio-dash-report"
```

It lives inside `.git/`, so it is never committed and never travels between
clones.

## Registering a new project

The registry is the only human input this system takes, and it is deliberately
changed **only by a commit** — never by an API. So registration is a pull to the
dashboard repo, not a POST.

```bash
git clone https://github.com/CodingDutchie/AI-project-dashboard /tmp/dash
```

Add one object to `registry/projects.json`:

```json
{ "slug": "myproject", "name": "My Project", "url": "https://myproject.com",
  "type": "owned", "kind": "web", "active": true,
  "repo": "CodingDutchie/myproject",
  "launched_at": "2026-08-01",
  "collectors": ["liveness", "github"] }
```

- `type`: `owned` | `client` | `product` | `other`
- `kind`: `web` | `app` | `game` | `physical` | `content`
- `collectors` is an allowlist — omit one and it never runs for that project
- `url`: **omit it if the project is not deployed.** A URL that does not serve is
  worse than no URL; it raises a `down` alert about a site that was never up
- `launched_at`: set it if you know it. It is the one date inference cannot
  recover, and without it a live site reads `launched` for 90 days from whenever
  the dashboard first saw it
- Add `"gsc"` and `"gsc_site_url": "sc-domain:example.com"` only if the property
  is verified in Search Console. Every property on this account is a domain
  property, so the `sc-domain:` form is almost certainly right

Then push to `main`. CI runs the tests, deploys, and reseeds the registry, so the
project is on the board in about ninety seconds — no need to wait for the cron.

**Ask the user before pushing.** Registering a project is a judgement about what
belongs in their portfolio, and `type`, `kind` and `launched_at` are theirs to
decide. Propose the entry, get a yes, then push.

## What not to do

- Do not report a repo that is not part of the portfolio. If the slug is unknown
  and the user does not want it registered, write the marker and move on.
- Do not invent a `next` because the field looks empty. No next action is a true
  and useful state — the board shows it plainly.
- Do not report the same commit twice. The marker exists for this.
