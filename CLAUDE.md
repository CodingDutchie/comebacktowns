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

## Decisions and deviations from BUILD_PLAN.md

- **Scope unit is the Census place** (incorporated city or village). CDPs are excluded, and
  "town-of" county subdivisions are not in v1: they are a separate geography with 10-digit
  GEOIDs and would add ~284 rows, far above the 120–180 gate. Village vs town-of is handled
  by scoring the village and labelling its `legal_type`. 148 places are in scope.
- **Regions follow NY's REDC boundaries** so no county is in two regions: Columbia and
  Greene (Catskill, Hudson) fall in the Capital Region, not the Hudson Valley. The owner
  confirmed the REDC grouping on 2026-09-19; moving a county is a one-line change in
  `config/scope.yml`.
- **Workers static assets instead of Cloudflare Pages.** wrangler 4 no longer creates Pages
  projects and recommends Workers; the site deploys with `wrangler deploy` from `site/dist`
  and the Phase 5 API will share the Worker (`run_worker_first` on `/api/*`).
- **`towns.county_fips`** was added to the §5 schema for joins against county-level ACS.
- **`gazetteer` is an extra feed** (place coordinates); popest supplies name, county and
  population. Both are keyless bulk files, so Phase 0 needs no Census API key.
- **R2 credentials are derived from `CLOUDFLARE_API_TOKEN`** (access key = token id, secret
  = SHA-256 of the token), so no extra secret is needed.
- **`seed/pilot_v0.csv` is the QA rule 4 baseline, re-baselined to the v1 engine.** The
  owner's 20 hand-scored pilot towns (five outside the v1 scope) arrived after v1 was
  published; only 5 of the 15 in-scope towns landed within ±3 of the engine (mean drift
  −6.6, rank correlation ≈0.4), a structural difference (the pilot's five-factor rubric had
  a stress factor v1 lacks and no main-street factor). Per §11.3 the owner chose to set
  `readiness` to the v1 output of 2026-09-19 and keep the hand score as `pilot_score`, so
  the rule guards the published methodology against regressions rather than the hand rubric.
- **Feeds added beyond the plan's list** to cover every scoring input: `tiger` (place
  polygons), `hospitals` (NYS DOH facility list), `osrm` (drive minutes to NYC, the nearest
  regional hub and the nearest hospitals, one cached `table` call per town at the demo
  server's 1 req/s), and the ACS tables B14001/B09001 at two non-overlapping vintages
  (2015-2019 and 2020-2024) for `school_enrollment_trend`. The plan's `broadband_100_share`
  cannot be sourced (the FCC broadband map's bulk files sit behind a login, 403), so the input
  is `broadband_subscription_share`, the ACS B28002 cable/fiber/DSL subscription share, and
  the methodology page says so.
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
  `pre1940_share` and `under_18_share` clear the rule for 88.5% of towns, so the coverage
  floor in `config/qa.yml` is 85% (the plan's 90% would fail every scheduled refresh on ACS
  sample noise; 85% still catches a feed that drops out).
- **`transform --allow-low-coverage`** writes rows even when the coverage gate fails; the
  shortfall is printed on every run either way.
- **Outbound HTTP is pinned to IPv4** (`make_client` binds `0.0.0.0`): a GitHub runner
  reached Overpass over IPv6 without a route and the run died with "Network is unreachable".
- **Scoring (Phase 3).** Weights and grade bands live in `config/scoring.v1.yml`; the curves
  live in code (`pipeline/score/curves.py`, `CURVES_V1`), each a named object whose
  `describe()` sentence feeds the methodology page. A factor is the mean of its usable
  inputs; readiness is the weighted sum renormalised over factors that have any usable
  input; coverage counts usable inputs over applicable ones (`dri_award_year` is only
  applicable to award winners). Grades are percentile curves within the two population
  bands; coverage under 60% means no grade. Every `score` run appends rows keyed on
  `computed_at`, so history is kept.
- **QA rule 4** compares `readiness` in `seed/pilot_v0.csv` (columns `geoid` or `slug` and
  `readiness`; a blank `readiness` marks a reference-only row) with the engine at ±3 points.
  `score --no-pilot` only covers a missing fixture; drift always stops the run.
- **Site (Phase 4).** Astro reads `site/data/*.json` written by `pipeline.cli export`
  (gitignored, rebuilt on every deploy); when absent it falls back to the committed
  `site/sample-data/` fixture (six towns) so CI and fresh clones still build. Labels, units
  and descriptions for every metric live in `config/metrics.yml`. Only `/compare` renders
  content client-side (it must read `?towns=` from the address; the data comes from the
  statically built `/data/compare.json`); every other page is static HTML with no content JS.
  The dataset download is licensed CC BY 4.0 (owner confirmed 2026-09-19); sources keep
  their own terms.
- **Grades were first published from a `score --no-pilot` run**, before the pilot fixture
  existed; the methodology version and computed-at stamp are on every town page.
- **API (Phase 5).** `worker/src/index.ts` runs first for every request (`run_worker_first`):
  redirects www to the apex, answers `/api/search`, `/api/filter`, `/api/compare` and
  `/api/health`, and hands everything else to the static assets. The town index (towns +
  latest scores run + latest headline facts) is built from D1 once and cached in KV
  (`CACHE`, TTL `INDEX_TTL` seconds) with a per-isolate memo in front; responses carry
  `Cache-Control` so the edge serves repeats. CORS reflects only origins in `SITE_ORIGINS`.
  Pure search/filter/compare logic is in `worker/src/logic.ts` and unit-tested with vitest.
- **Custom domain.** `comebacktowns.com` and `www.comebacktowns.com` are Workers custom
  domains declared in `wrangler.toml` (`routes`), created by `wrangler deploy`. Email routing
  for `data@` is separate and untouched.
- **Automation (Phase 6).** `refresh-monthly.yml` (2nd of the month: gazetteer, popest,
  tiger, zillow, osm) and `refresh-annual.yml` (15 January: those plus acs, permits, nrhp,
  rail, hospitals, osrm, dri) call the reusable `refresh.yml`, which ingests one source at a
  time, runs `transform --dry-run` and `score --dry-run --metrics-csv` first, and only then
  loads metrics and scores; `publish.yml` (also on pushes to main touching the site) exports,
  builds, deploys, purges the API's KV index and smoke-checks the live domain. Any failure
  runs `report-failure.yml`, which opens or updates an issue labelled `refresh-failure`
  naming the source or step, and nothing is published. Scheduled runs never skip QA rule 4:
  drift beyond ±3 stops them at the scoring dry run with an issue; `skip_pilot` on a manual
  dispatch only covers a missing fixture.
- **Momentum (Phase 7).** The second score from BUILD_PLAN.md §0, built by the readiness
  engine from `config/momentum.v1.yml` (curves in `MOMENTUM_CURVES_V1`), written to its own
  `momentum` table (migration 0002) by `cli.py momentum`, and exported as `momentum.json`.
  Three inputs, each a change judged against a benchmark: Zillow home value change over one
  year and population change since 2020, both minus the median across every New York place
  in the same source file (`*_ny_median` rows, context-only like `metro_median_home_value`);
  and the change in the town's own three-year permit rate over two years. Keeping pace
  scores 50; labels are absolute (rising ≥ 60, fading < 40), not curved, because momentum
  is direction, not rank; under 60% coverage (fewer than two of three inputs) there is no
  label. Rent change is produced and shown but not scored (Zillow covers 23 of 148 towns).
  Momentum inputs are printed by `transform` but not gated by the 85% floor.
- **Momentum v2 is the active version** (`MOMENTUM_VERSION` in `pipeline/settings.py`, the
  `momentum` and `export` defaults, and the Worker's momentum query; readiness stays v1).
  It adds the `irs` feed (SOI county-to-county migration, inflow and outflow CSVs per
  filing-year pair, latin-1, `-1` = suppressed): `county_net_migration_rate` is net
  individuals per 1,000 of the county's year-1 filing population, benchmarked against the
  median New York county. County level is the finest the IRS publishes, so every town in a
  county carries the same figure, named `county_*` and explained on the page. A label needs
  three of the four scored inputs. HUD's USPS vacancy data is restricted to governmental and
  non-profit registered users (§11.4); the owner decided on 2026-09-19 to leave vacancy out.
  If that ever changes it is `momentum.v3.yml`, never an edit to v2.
  New IRS years are added to `years` in `config/sources.yml`, like permits. The Worker
  index key is `index:v3`.
- **Design ("Ledger").** Dark slate header and hero bands over a light ledger body, IBM Plex
  Sans for text and IBM Plex Mono for every figure, code and label (Google Fonts, preconnected,
  `display=swap`); colour tokens and all component CSS live in `site/src/layouts/Base.astro`,
  with a dark scheme under `prefers-color-scheme`. The mark is the "Return" roofline-arrow
  (`site/src/components/Logo.astro`, `site/public/favicon.svg`); the social card and Apple
  touch icon are rendered from it by `site/scripts/render-images.mjs` with the pre-installed
  Chromium (`CHROMIUM_PATH=/opt/pw-browsers/chromium-*/chrome-linux/chrome`) and committed.
  Grade tiles (`Grade.astro`) and momentum chips (`Momentum.astro`, "▲ RISING 74", or
  "NO LABEL · 2 OF 4" when the inputs are short) share the geometry. The source strip on the
  home page is typographic on purpose: agency seals and logos imply endorsement and several
  are restricted marks, so sources are named, never logoed. Town pages explain each score in
  a sentence generated from the data (`readinessMeaning`, `momentumMeaning` in
  `site/src/lib/format.ts`) and summarise each factor's inputs on one line (`inputSummary`).
- **Snapshot resolution.** Each transform reads the latest snapshot of its own source on or
  before the run date and stamps rows with that date, so a monthly run re-pulls only the
  monthly feeds and every other figure keeps citing its most recent pull.
