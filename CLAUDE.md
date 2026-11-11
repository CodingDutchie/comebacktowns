# Comeback Towns — working notes for Claude Code

The build spec is `BUILD_PLAN.md`. Read it first; this file is the short version plus the
decisions made while building.

## Run things

```sh
uv sync --all-groups                       # Python 3.12 env (uv installs the interpreter)
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
uv run python -m pipeline.cli scope --dry-run        # build the town list, no writes
uv run python -m pipeline.cli scope                  # ...and write the towns table in D1
uv run python -m pipeline.cli ingest --all           # every feed -> R2 raw/{source}/{as_of}/
uv run python -m pipeline.cli ingest permits nrhp    # ...or named feeds; reruns are no-ops
uv run python -m pipeline.cli discover               # permits/IRS years newer than config, HEAD only
uv run python -m pipeline.cli transform --dry-run    # raw -> metrics rows, QA, coverage table
uv run python -m pipeline.cli transform              # ...and upsert the metrics table in D1
uv run python -m pipeline.cli score --explain catskill-ny   # full audit trail for one town
uv run python -m pipeline.cli score --dry-run        # score + grade every town, run QA rule 4
uv run python -m pipeline.cli score                  # ...and append a scores run to D1
uv run python -m pipeline.cli momentum --dry-run     # momentum score + rising/steady/fading label
uv run python -m pipeline.cli momentum               # ...and append a momentum run to D1
npx wrangler d1 migrations apply comebacktowns --remote   # schema, from migrations/
uv run python -m pipeline.cli export                 # D1 -> site/data/*.json + dataset CSV
cd site && npm ci && npm run check && npm run build  # Astro static build -> site/dist
cd worker && npm ci && npm run check && npm test    # API worker (pure logic unit-tested)
npx wrangler deploy                                  # site/dist + /api/* as one Worker
```

Environment the pipeline reads (never defaults, never literals):
`CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` (D1 over HTTP, R2 over S3 with credentials
derived from the token per Cloudflare's docs), `CENSUS_API_KEY` (Phase 1 ACS). Optional:
`COMEBACKTOWNS_RAW_STORE=local` writes raw snapshots to `data/raw/` instead of R2;
`R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY` override the derived R2 credentials;
`D1_DATABASE_ID` overrides the id in `wrangler.toml`.

## Guardrails (BUILD_PLAN.md §10)

- Never `actions/upload-artifact`. Never commit raw data. R2 only.
- Never print, log or echo a secret; run URLs through `pipeline.settings.redact_url` before
  logging. Third-party HTTP loggers are set to WARNING in the CLI for the same reason.
- Scoring weights change only by adding `config/scoring.v2.yml`, never by editing v1.
- No new paid Cloudflare products or paid APIs without asking the owner.
- An unreachable source stops the run. Never substitute a source, interpolate, or estimate a
  missing number. Missing is missing and the site says so.
- No metric enters the score unless it is in the active `config/scoring.*.yml`; the same
  for momentum and `config/momentum.*.yml`.
- Brand strings come from `config/site.yml` (`SITE_NAME`, `SITE_DOMAIN`, `CONTACT_EMAIL`).
  Always the plural `comebacktowns.com`.
- Conventional commits, one PR per phase, tests with each module.

## Layout

`pipeline/` (ingest, transform, score, load, qa, `cli.py`), `config/`, `migrations/` (D1,
applied with wrangler), `site/` (Astro 5, static), `worker/` (Phase 5 API), `tests/`,
`seed/` (pilot regression fixture, see below), `.github/workflows/`.

## Decisions → `docs/DECISIONS.md`
Why the project deviates from BUILD_PLAN.md (scope unit, REDC regions, Workers instead of Pages, ingest,
scoring versions, site build, SEO, analytics) is in **`docs/DECISIONS.md`**. Read the relevant entry before
changing any of those areas; add new decisions there.

### Rules from the decisions (always apply)
- Straight-line `crow_miles_*` rows are never substituted for `drive_min_*`.
- Scoring configs are versioned: a change is a new file (e.g. `momentum.v3.yml`), never an edit to a published one.
- Scheduled runs never skip QA rule 4 (drift beyond ±3 stops at the scoring dry run with an issue).
- In ingest, only a 404-class status means "not released yet"; anything else raises, so an outage is never read as an unreleased file.
- Every generated sentence is built from the data with its period, never hand-written; nothing claims what the data cannot show.
- Sources are named, never shown with seals or logos (endorsement / restricted marks).
- Only `/compare` renders content client-side; every other page is static HTML with no content JS.
- The analytics note says what the beacon does and does not do; it never says "no analytics".

## Reporting to the portfolio dashboard

At the end of a working session that shipped something, report what actually
landed and what is next — use the `portfolio-report` skill in `.claude/skills/`.
Report outcomes, not intentions, and do not report a stage: the dashboard infers
that from commits, traffic and uptime.

A Stop hook asks for this automatically when a session has committed and not
reported, and goes quiet once it has. Both are inert without `INGEST_TOKEN` and
the two `CF_ACCESS_*` variables, so a machine without them never sees a prompt.

## Before launch and after any domain or routing change

Run the `launch-check` skill (`node .claude/skills/launch-check/check.mjs https://<site>`)
and fix every FAIL with its recipe. It catches the duplicate hosts, soft-404s,
canonical mismatches and stale analytics beacons that otherwise surface weeks later
in Search Console.

## Operating policy (owner's, 2026-11-11) and standing rulings

The owner is **Emory** (Emory de Koop); address them as Emory, never "Eddy". The project runs
without its owner, so sessions decide, record why in `docs/DECISIONS.md`, and carry on:

1. **Decide, do not hand back.** Ask Emory only for what only they can do: money, access,
   limits, or messages in their name. Ask once, with the exact step, in `BACKLOG.md` under
   "Needs Emory", and keep working on everything else.
2. **Uncertain means not shipped**, never "queued for a person". Hold it back, record why, and
   retry on the next cycle. QA rule 4 and the coverage floor already work this way.
3. **Model work runs in Claude sessions** (interactive or scheduled, on the owner's plan).
   Deployed code (pipeline, Worker, Workflow, site, hooks) does only deterministic work and
   never calls a model. A Console API key or Workers AI is justified only when end users
   trigger the model live or a step must run unattended more often than hourly; even then it
   is spend, so it goes to Emory as a written case (what it buys, what it costs, a hard monthly
   cap) and nothing is added or raised until they say yes. The Guardrails above stand.
4. **Two independent readings plus deterministic checks replace human review** (rulings R1
   and R2). Report *agreement* between readings, never "accuracy", unless a person has
   checked a sample.
5. **Rulings are made once, recorded, and applied.** The list below is the current set.
6. **End with what was done and what was found**, not a menu of options.

BUILD_PLAN.md §11 ("stop and ask the owner") still holds for its items 1, 2 and 4 (tokens,
money, a licence or registration): those are access and money. Its items 3 and 5 are covered
by the rulings. `BACKLOG.md` is the task list: read it first, tick what you finish with the
date and PR, add what you find; items under "Needs Emory" are theirs to do, so do not start
them, and keep working on everything else. Model use: Sonnet by default, Haiku for small mechanical jobs,
Opus only where a mistake is costly. Keep to the design language (tokens and shared
components); extend it rather than adding one-off styles.

### Rulings

- **R1 Merging.** A pull request merges without Emory when (a) CI is green on its head,
  (b) the author ran the repo's checks locally, and (c) a second, independent reading of the
  diff (a fresh-context reviewer given only the diff, this file and `docs/DECISIONS.md`) found
  nothing blocking. The PR records both readings and whether they agreed. Disagreement means
  not shipped: hold, record why on the PR, retry next cycle. R1 covers code, config, docs and
  workflows alike; it never covers money, access or messages in the owner's name.
- **R2 QA rule 4 drift.** Never bypassed, never widened. A drift is re-baselined, for that one
  row only, when two independent readings of the raw snapshots agree it is a genuine input
  change: the same drift on two fresh snapshots from different days, the changed input's raw
  documents carrying current base dates, and the method unchanged. Record it in
  `docs/DECISIONS.md` and `seed/README.md`. Anything else holds the publish and retries next
  cycle. Saugerties (2026-11-06) is the precedent.
- **R3 Retries.** A failed or skipped monthly refresh is retried by `refresh-watchdog.yml` on
  the 3rd, 5th and 9th; the `refresh-failure` issue is the record, not a request to a person.
- **R4 Overpass servers.** A server joins `workflow_servers` or `fallback_urls` only after
  passing the probe (current base, New York data) on two different days. Hosting jurisdiction
  is not a criterion: the queries carry no personal data and the data is public. The Russian
  mirrors are out on the Nov 2026 probe results (504, 522), not on jurisdiction.
- **R5 Expansion beyond New York** waits on a measured gate, not a decision: New York town
  pages earning at least 300 Google clicks in a 28-day window and two consecutive clean
  monthly refreshes. Until then the backlog carries it under Waiting.
- **R6 Claims.** Nothing on the site or in the docs claims accuracy. The pilot fixture
  measures agreement with the published engine; every figure says what it is and when it was
  pulled.
