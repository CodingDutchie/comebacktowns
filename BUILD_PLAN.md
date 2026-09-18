# BUILD_PLAN.md — Comeback Towns

Execution plan for Claude Code. You are building this repo end to end. Work the phases in
order; each has a **Done when** gate — do not start the next phase until it is true. Open a
PR per phase. Where a step needs a human (credentials, a paid upgrade, a judgement call),
stop and ask rather than improvising: §11 lists those.

Project doc with the full research and reasoning behind this plan: the Comeback Towns
working doc in the owner's Claude project. This file is the authoritative build spec.

---

## 0. What you are building

**comebacktowns.com** — a public data site that scores New York towns on two things:

- **Readiness** — are the ingredients for a revival present? (slow-moving, A–F grade). v1.
- **Momentum** — is anything actually happening? (rising / steady / fading). v2.

One dataset, three audiences: people considering a move, small investors, town officials.
The product's claim is *"this town is turning around, and here is the evidence."* Every
competitor sells the town; this one says when a town is stalling. That only works if
**every number on the site carries its source and as-of date**, so provenance is a
correctness requirement, not a nicety.

`seed/pilot_v0.csv` holds 20 towns scored by hand during research. It is the regression
fixture: the rebuilt pipeline must reproduce those scores within ±3 points.

---

## 1. Prerequisites and credentials

**Already provisioned by the owner:**

| Item | Where | Notes |
|---|---|---|
| Domain `comebacktowns.com` | Cloudflare | Registered and on Cloudflare DNS |
| `CENSUS_API_KEY` | GitHub Secrets, and `.dev.vars` locally | Free Census API key, already activated |
| Contact address | `data@comebacktowns.com` | Cloudflare Email Routing, forwards to the owner |
| GitHub repo | `CodingDutchie/comebacktowns` | Public |

**You will need the owner to create (ask in Phase 0, do not attempt to work around):**

| Secret | Purpose | How the owner makes it |
|---|---|---|
| `CLOUDFLARE_API_TOKEN` | wrangler: D1, R2, Pages, Workers | Cloudflare dashboard → My Profile → API Tokens → Create Token, with Workers Scripts:Edit, D1:Edit, Workers R2 Storage:Edit, Cloudflare Pages:Edit on the account |
| `CLOUDFLARE_ACCOUNT_ID` | wrangler target | Cloudflare dashboard sidebar |

Secret handling rules, which matter more than usual because the repo is public:

- Read secrets only from `os.environ` / `${{ secrets.* }}`. Never a literal, never a default
  value, never in a committed config file, never in a log line.
- Before logging any request URL, strip the `key=` query parameter.
- `.dev.vars` and `.env*` are gitignored **before the first commit**.
- Run `git log -p --all -S "CENSUS_API_KEY=" | head` once in Phase 0 and confirm it is empty.
- If a secret is missing at runtime, fail immediately with a message naming which one. Never
  degrade to an unkeyed request.

---

## 2. Hard constraints

| Constraint | Consequence |
|---|---|
| GitHub Actions artifact storage is **full** (0.5/0.5 GB, account-wide) | **Never use `actions/upload-artifact`.** Stream downloads straight to R2; keep nothing on GitHub. |
| Actions minutes are free on public repos with standard runners | Repo stays public. Do not add self-hosted runners. |
| `api.census.gov` requires a key | Already provisioned. Batch requests by state, not per town. |
| Some feeds are 100 MB+ CSVs | Ingest runs in Actions, never in a Worker. Stream to R2; never load a whole file into memory. |
| ACS margins of error are wide for small places | The suppression rules in §7 are mandatory. |
| Cloudflare Free tier | D1 and Pages free limits are ample at this scale. **Do not enable a paid product without asking.** |
| Census Reporter blocks automated access | Do not route around it — use the Census API instead. |

**Brand strings live in one place:** `config/site.yml` (`SITE_NAME: Comeback Towns`,
`SITE_DOMAIN: comebacktowns.com`, `CONTACT_EMAIL: data@comebacktowns.com`). Never hardcode
them in templates. The singular `comebacktown.com` belongs to someone else — always plural.

---

## 3. Stack

- **Pipeline:** Python 3.12, `uv`, `httpx`, `polars`, `pydantic`, `boto3` (R2 via S3 API)
- **Storage:** R2 for raw snapshots (private), D1 for canonical tables
- **Site:** Astro 5, static output, Cloudflare Pages
- **API:** one Worker for search / filter / compare, reading D1
- **CI:** GitHub Actions
- **Quality:** `ruff`, `pytest`, `mypy` (non-strict)

---

## 4. Repo layout

```
.
├── BUILD_PLAN.md
├── CLAUDE.md            # short: how to run things, the guardrails in §10
├── pipeline/
│   ├── ingest/          # one module per feed: fetch(as_of) -> r2_key
│   │   ├── acs.py  popest.py  permits.py  zillow.py  osm.py  nrhp.py  rail.py  dri.py
│   ├── transform/       # raw -> tidy metrics rows
│   ├── score/           # scoring engine + config loader
│   ├── load/            # D1 writer (batched SQL over the HTTP API)
│   ├── qa/              # validation rules + pilot regression
│   └── cli.py           # python -m pipeline.cli <command>
├── config/
│   ├── site.yml
│   ├── scope.yml        # counties + population bounds
│   ├── scoring.v1.yml   # weights + curves (versioned; never edited in place)
│   └── sources.yml      # per feed: url, cadence, licence, attribution, user_agent
├── site/                # Astro
├── worker/              # search/compare API
├── migrations/          # D1 SQL
├── seed/pilot_v0.csv
├── tests/
└── .github/workflows/
```

---

## 5. Data model (D1)

```sql
CREATE TABLE towns (
  geoid TEXT PRIMARY KEY,          -- Census place GEOID, e.g. 3613002
  name TEXT NOT NULL,              -- "Catskill"
  legal_type TEXT NOT NULL,        -- city | village | town
  county TEXT NOT NULL,
  region TEXT NOT NULL,            -- Hudson Valley | Capital Region | Mohawk Valley
  lat REAL NOT NULL, lon REAL NOT NULL,
  pop_latest INTEGER, pop_latest_year INTEGER,
  slug TEXT UNIQUE NOT NULL        -- catskill-ny
);

CREATE TABLE metrics (
  geoid TEXT NOT NULL,
  metric TEXT NOT NULL,            -- median_home_value | vacancy_rate | permits_per_1k | ...
  period TEXT NOT NULL,            -- "2020-2024" | "2025" | "2026-08"
  value REAL,
  moe REAL,                        -- null when not applicable
  suppressed INTEGER NOT NULL DEFAULT 0,
  source_id TEXT NOT NULL,         -- key in config/sources.yml
  as_of TEXT NOT NULL,             -- ISO date pulled
  r2_key TEXT NOT NULL,            -- exact raw file this came from
  PRIMARY KEY (geoid, metric, period)
);

CREATE TABLE scores (
  geoid TEXT NOT NULL,
  config_version TEXT NOT NULL,
  computed_at TEXT NOT NULL,
  readiness REAL NOT NULL,         -- 0-100
  grade TEXT,                      -- A..F, null when coverage is below the floor
  factor_scores TEXT NOT NULL,     -- JSON
  factor_inputs TEXT NOT NULL,     -- JSON: every input value used
  coverage REAL NOT NULL,          -- 0-1
  PRIMARY KEY (geoid, config_version, computed_at)
);
```

**Rule: nothing reaches `scores` that cannot name its `r2_key`.**

---

## 6. Scoring — v1 is readiness only

`config/scoring.v1.yml`:

```yaml
version: v1
factors:
  access:         {weight: 0.25, inputs: [drive_min_nyc, drive_min_regional_hub, miles_to_rail_station]}
  building_stock: {weight: 0.15, inputs: [pre1940_share, has_nrhp_district]}
  main_street:    {weight: 0.15, inputs: [osm_business_per_1k]}
  price_headroom: {weight: 0.15, inputs: [median_home_value, metro_median_home_value]}
  services:       {weight: 0.15, inputs: [broadband_100_share, school_enrollment_trend, hospital_within_20min]}
  civic_capacity: {weight: 0.15, inputs: [dri_award_amount, dri_award_year]}
grading:
  method: curve
  bands: {A: 90, B: 75, C: 50, D: 25, F: 0}
  curve_within: population_band     # under 5,000 and 5,000+ are curved separately
min_coverage: 0.6
```

- Each input normalises 0–1 through an explicit, named curve in code. Every curve is
  documented on the methodology page — if you cannot explain it in a sentence, it is wrong.
- `price_headroom` is **not** monotonic. Cheapest is not best: the curve peaks near 60% of
  the metro median and falls off both above (no headroom) and far below (no demand). This is
  what makes an already-revived town score mid-pack, which is intended.
- A missing input never scores zero. It is excluded, and `coverage` drops. Below
  `min_coverage`, publish the page with the data and **no grade**.
- Grades are curved within population bands, because ACS quality differs sharply between
  small villages and cities.

---

## 7. Data quality rules (in `pipeline/qa/`; a breach fails the run)

1. Suppress any ACS value whose MOE exceeds 40% of the estimate. Mark `suppressed=1` — a
   suppressed value is not the same as a missing one, and the site says so.
2. Permits use a 3-year rolling mean. One 60-unit project must not spike a small town.
3. Every metric row carries `as_of` and `r2_key`, or the load rejects it.
4. Pilot regression: the 20 towns in `seed/pilot_v0.csv` must land within ±3 points. Larger
   drift is a deliberate methodology change, and needs a new config version plus a note in
   the PR explaining what changed and why.
5. Per-metric sanity bounds (e.g. `0 <= vacancy_rate <= 0.6`, `median_home_value > 10000`).
   Out of bounds fails loudly rather than publishing.
6. Village vs town-of is a known trap — they are different Census places with the same name.
   Keep both where they differ and label them on the page.

---

## 8. Phases

### Phase 0 — Repo, credentials, scope

- Scaffold: `uv` project, ruff, pytest, mypy, Astro under `site/`, `.gitignore` covering
  `.dev.vars`, `.env*`, `data/`, `*.csv` outside `seed/`.
- Write `CLAUDE.md`: how to run the CLI, the guardrails from §10, and a pointer to this file.
- Confirm `CENSUS_API_KEY` resolves from the environment. Ask the owner for the Cloudflare
  token and account ID (§1) and stop until they exist.
- Create the Cloudflare resources with wrangler: D1 database `comebacktowns`, R2 bucket
  `comebacktowns-raw` (private), Pages project `comebacktowns`. Commit `wrangler.toml` with
  the binding names but **never** the account ID or token.
- `config/scope.yml`: Hudson Valley, Capital Region and Mohawk Valley counties; population
  1,000–50,000.
- `pipeline/cli.py scope` builds the town list from the Census gazetteer plus population
  estimates and writes the `towns` table.
- Run the secret-history check from §1.

**Done when:** `SELECT count(*) FROM towns` returns roughly 120–180 rows, every row has
coordinates and a unique slug, and `uv run pytest` passes.

### Phase 1 — Ingest

Each feed module exposes `fetch(as_of) -> r2_key`, is idempotent and resumable, streams to
`raw/{source_id}/{as_of}/{filename}` in R2, and writes nothing over 50 MB to local disk.

Build in this order, one PR each: `acs` → `popest` → `permits` → `nrhp` → `rail` → `osm` →
`zillow` → `dri`.

- **acs** — 5-year estimates, all NY places: B25077 (home value), B25064 (rent), B19013
  (income), B25002 (occupancy), B25034 (year built), B28002 (broadband), B17001 (poverty),
  B08303 (commute). Keep MOEs; they drive rule 1.
- **popest** — Census sub-county population estimates, bulk CSV.
- **permits** — Census Building Permits Survey, place level, annual.
- **nrhp** — National Register data for historic districts, with coordinates.
- **rail** — Amtrak and commuter rail station locations; compute distance per town.
- **osm** — Overpass: amenity and shop counts in the place polygon. Rate-limited and
  variable, so cache aggressively, back off politely, and record the query in `sources.yml`.
- **zillow** — ZHVI and ZORI bulk CSVs; expect gaps for small villages and record them as
  gaps, never as zeros.
- **dri** — DRI and NY Forward awards scraped from governor.ny.gov into
  (place, program, year, amount). Snapshot the HTML into R2 too, since it is a scrape.

Every outbound request sets a descriptive User-Agent including `data@comebacktowns.com`,
retries with exponential backoff, and honours robots and rate limits.

**Done when:** `cli.py ingest --all` finishes under 30 minutes, every raw file is in R2 under
a dated key, and a second run is a no-op.

### Phase 2 — Transform and load

- Map every raw file to tidy `metrics` rows.
- Drive times: compute once per town and cache. Straight-line distance is a fallback and is
  flagged as such in the metric name, never silently substituted.
- D1 writes are batched over the HTTP API, in transactions, and are idempotent.

**Done when:** `metrics` covers every factor input for ≥90% of in-scope towns, and QA rules
1, 2, 3 and 5 pass.

### Phase 3 — Scoring

- Implement the engine against `config/scoring.v1.yml`; write `scores`.
- `cli.py score --explain <geoid>` prints every input, its raw value, its normalised value
  and its contribution to the total. This command is what the methodology page is built from.

**Done when:** QA rule 4 passes against the pilot fixture, and `--explain` output for
Catskill reads as a complete audit trail.

### Phase 4 — Site

Routes:

- `/` — what this is, top rankings, search
- `/town/{slug}` — grade header, five key numbers (home value, rent, drive time, main street
  businesses, permits last year), six factor cards that expand into their inputs, peer
  comparison, and a sources block with per-figure as-of dates
- `/rankings/{ranking}` — highest readiness, best price headroom, best value within an hour
  of a city
- `/compare?towns=a,b,c`
- `/methodology` — weights, every curve, suppression rules, dataset download
- `/sources` — every feed with licence, attribution and last pull
- `/about` — who makes this, how to send a correction

Requirements: static build, no client JS for content, JSON-LD (`Dataset` on methodology,
`Place` on towns), sitemap, canonical URLs, dark and light, mobile-first, LCP under 2s.
A suppressed or missing value is rendered as an explicit "not available at this sample size"
with a link to the explanation — never a blank cell, never a zero.

**Done when:** `npm run build` emits a page per town plus rankings, and Lighthouse SEO and
performance are ≥95 on a town page.

### Phase 5 — Worker API

`GET /api/search?q=`, `/api/filter?...`, `/api/compare?towns=` — D1-backed, cached in KV,
CORS restricted to the site origin.

**Done when:** search-as-you-type returns under 100 ms at the edge.

### Phase 6 — Automation

- `.github/workflows/ingest-monthly.yml` (OSM, Zillow, rescore, redeploy) and
  `ingest-annual.yml` (ACS, permits, popest), both `workflow_dispatch`-able.
- Concurrency group per workflow. On failure: open an issue naming the failing source and
  stop. Never publish a partial refresh.
- Confirm no workflow logs a secret or a signed URL. Logs are world-readable.

**Done when:** a manual dispatch runs end to end, the deployed site shows new as-of dates,
and zero artifacts were uploaded.

---

## 9. Definition of done for v1

About 150 towns live at comebacktowns.com, each with a readiness grade or an explicit reason
there isn't one, every figure sourced and dated, a methodology page a town official could
argue with, a downloadable dataset, and a monthly refresh that runs without being touched.

---

## 10. Guardrails

- **Never** `actions/upload-artifact`. **Never** commit raw data. R2 only.
- **Never** print, log or echo a secret; strip `key=` before logging any URL.
- Scoring weights change only by adding a new config version — never by editing `v1`.
- No new paid Cloudflare products, no new paid APIs, without asking.
- If a source is unreachable, stop and report. Do not silently substitute another source,
  and never fill a gap with an estimate, an interpolation or a model guess. A missing number
  is a missing number, and the site is built to show that honestly.
- Do not add a metric to the score that is not in `config/scoring.v1.yml`.
- Conventional commits, one PR per phase, tests with each module.
- When something in this plan turns out to be wrong — a feed that moved, a geography that
  doesn't line up — say so and propose the fix rather than quietly working around it.

---

## 11. Stop and ask the owner

1. The Cloudflare API token and account ID (Phase 0).
2. Anything that would cost money.
3. A scoring change that moves pilot scores more than ±3 points.
4. A data source that turns out to need a licence, a paid tier or a registration you cannot
   complete.
5. Any design decision that changes what the site *claims* — for example withholding grades
   for a whole class of towns, or changing how suppression is presented.

---

## 12. Out of scope for v1

Momentum scoring and its feeds (IRS SOI migration, HUD USPS vacancy, price and permit time
series), the mover/investor/planner lenses, email alerts, statewide coverage, and the
long-form case studies. All are specified in the project doc as v2/v3.
