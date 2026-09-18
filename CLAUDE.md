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
uv run python -m pipeline.cli transform --dry-run    # raw -> metrics rows, QA, coverage table
uv run python -m pipeline.cli transform              # ...and upsert the metrics table in D1
uv run python -m pipeline.cli score --explain catskill-ny   # full audit trail for one town
uv run python -m pipeline.cli score --dry-run        # score + grade every town, run QA rule 4
uv run python -m pipeline.cli score                  # ...and append a scores run to D1
npx wrangler d1 migrations apply comebacktowns --remote   # schema, from migrations/
uv run python -m pipeline.cli export                 # D1 -> site/data/*.json + dataset CSV
cd site && npm ci && npm run check && npm run build  # Astro static build -> site/dist
npx wrangler deploy                                  # site/dist (+ API later) as one Worker
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
- No metric enters the score unless it is in the active `config/scoring.*.yml`.
- Brand strings come from `config/site.yml` (`SITE_NAME`, `SITE_DOMAIN`, `CONTACT_EMAIL`).
  Always the plural `comebacktowns.com`.
- Conventional commits, one PR per phase, tests with each module.

## Layout

`pipeline/` (ingest, transform, score, load, qa, `cli.py`), `config/`, `migrations/` (D1,
applied with wrangler), `site/` (Astro 5, static), `worker/` (Phase 5 API), `tests/`,
`seed/` (pilot regression fixture, see below), `.github/workflows/`.

## Decisions and deviations from BUILD_PLAN.md

- **Scope unit is the Census place** (incorporated city or village). CDPs are excluded, and
  "town-of" county subdivisions are not in v1: they are a separate geography with 10-digit
  GEOIDs and would add ~284 rows, far above the 120–180 gate. Village vs town-of is handled
  by scoring the village and labelling its `legal_type`. 148 places are in scope.
- **Regions follow NY's REDC boundaries** so no county is in two regions: Columbia and
  Greene (Catskill, Hudson) fall in the Capital Region, not the Hudson Valley. Moving them is
  a one-line change in `config/scope.yml` if the owner prefers the colloquial grouping.
- **Workers static assets instead of Cloudflare Pages.** wrangler 4 no longer creates Pages
  projects and recommends Workers; the site deploys with `wrangler deploy` from `site/dist`
  and the Phase 5 API will share the Worker (`run_worker_first` on `/api/*`).
- **`towns.county_fips`** was added to the §5 schema for joins against county-level ACS.
- **`gazetteer` is an extra feed** (place coordinates); popest supplies name, county and
  population. Both are keyless bulk files, so Phase 0 needs no Census API key.
- **R2 credentials are derived from `CLOUDFLARE_API_TOKEN`** (access key = token id, secret
  = SHA-256 of the token), so no extra secret is needed.
- **`seed/pilot_v0.csv` is not in the repo.** Until the owner adds it, QA rule 4 (pilot
  regression) cannot run and Phase 3 cannot close.
- **Feeds added beyond the plan's list** to cover every scoring input: `tiger` (place
  polygons), `hospitals` (NYS DOH facility list), `osrm` (drive minutes to NYC, the nearest
  regional hub and the nearest hospitals, one cached `table` call per town at the demo
  server's 1 req/s), and the ACS tables B14001/B09001 at two non-overlapping vintages
  (2015-2019 and 2020-2024) for `school_enrollment_trend`. `broadband_100_share` cannot be
  sourced: the FCC broadband map's bulk files sit behind a login (403), so the metric will be
  the ACS B28002 broadband *subscription* share and the methodology page will say so.
- **Metro-North's West-of-Hudson stations** (Port Jervis line) are not in the MTA GTFS feed
  and NJ Transit's requires a developer registration, so `config/rail_stations_manual.yml`
  carries the nine stations transcribed from MTA station pages, with the source named.
- **DRI/NY Forward is a scrape** of ny.gov program and round pages (HTML snapshotted to R2,
  parsed by `pipeline/transform/dri.py`). Amounts come from the page only when they match a
  size the programs actually award; otherwise the program's standard award is used and the
  row says `program_standard`.
- **Overpass and the Census API cannot be reached from the Claude Code container** (the
  proxy drops Overpass; the Census API needs the key that lives in GitHub Secrets). Those
  two feeds run through `.github/workflows/ingest.yml` (`workflow_dispatch`).
- **Metric naming in Phase 2.** Every ACS-derived row keeps its margin of error and the 40%
  rule sets `suppressed`; ratios use the Census proportion formula. `metro_median_home_value`
  is the CBSA median where the Building Permits Survey places the town in a CBSA, else the
  county median (each row cites the file it came from). Straight-line distances are separate
  `crow_miles_*` rows from Gazetteer coordinates, never substituted for `drive_min_*`.
- **The 40% rule and ACS trends.** `school_enrollment_trend` (2015-19 vs 2020-24 K-12
  enrollment) is suppressed for 145 of 148 towns: the MOE of a difference of two five-year
  estimates is always wider than the small change itself at village scale. The rule is kept;
  the owner swapped the services input for `under_18_share` (B09001 over B01003, a level
  that clears the rule) before v1 was ever published. The trend rows are still produced.
  `pre1940_share` clears the rule for 88.5% of towns, just under the 90% coverage floor.
- **`transform --allow-low-coverage`** writes rows even when the coverage gate fails; the
  gate itself (`config/qa.yml`) stays at 90% so the shortfall is printed on every run.
- **Scoring (Phase 3).** Weights and grade bands live in `config/scoring.v1.yml`; the curves
  live in code (`pipeline/score/curves.py`, `CURVES_V1`), each a named object whose
  `describe()` sentence feeds the methodology page. A factor is the mean of its usable
  inputs; readiness is the weighted sum renormalised over factors that have any usable
  input; coverage counts usable inputs over applicable ones (`dri_award_year` is only
  applicable to award winners). Grades are percentile curves within the two population
  bands; coverage under 60% means no grade. Every `score` run appends rows keyed on
  `computed_at`, so history is kept.
- **QA rule 4 cannot run** until `seed/pilot_v0.csv` exists (columns `geoid` or `slug`, and
  `readiness`); `score --no-pilot` states that explicitly when writing without it.
- **Site (Phase 4).** Astro reads `site/data/*.json` written by `pipeline.cli export`
  (gitignored, rebuilt on every deploy); when absent it falls back to the committed
  `site/sample-data/` fixture (six towns) so CI and fresh clones still build. Labels, units
  and descriptions for every metric live in `config/metrics.yml`. Only `/compare` renders
  content client-side (it must read `?towns=` from the address; the data comes from the
  statically built `/data/compare.json`); every other page is static HTML with no content JS.
  The dataset download is licensed CC BY 4.0 (owner to confirm); sources keep their own terms.
- **Grades are published from a `score --no-pilot` run** until `seed/pilot_v0.csv` exists;
  the methodology version and computed-at stamp are on every town page.
