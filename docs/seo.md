# Search and answer-engine notes

Research done 2026-09-19 with free sources only (Google Trends via trendspy, Google
autocomplete, hand-sampled search results, a crawl of the live site). Every figure below
carries a tag: **measured** (from an API, with the date), **estimated** (derived, method
shown) or **inferred** (reasoned from result pages, no volume data). Google Ads and Bing
Webmaster volume were not configured, so there is no absolute volume anywhere here.

## What people type

- **measured, Google Trends, US, 5 years, 2026-09-19.** The head terms are small and flat:
  "moving to upstate new york" sits near the floor of the index; "hudson valley real
  estate" is flat over five years with a July peak about 2.1× the annual mean; "catskills
  real estate" fell about 80% from its 2021 peak; "kingston ny" and "mohawk valley" are flat.
  Nothing here is a head term worth chasing on its own.
- **autocomplete rank, 14 seeds, 1,268 suggestions, 2026-09-19.** The demand is long-tail
  and question-shaped, and it maps onto pages we can build from data:
  - "is kingston ny a good place to live", "is catskill ny a good place to live", "should i
    move to kingston ny", "is hudson valley a good place to live" → the per-town question.
  - "best towns in hudson valley to live", "cheapest towns in hudson valley", "most
    affordable towns in the hudson valley", "best places to buy a house upstate ny" →
    region pages with a cheapest-towns table and a most-affordable ranking.
  - "towns near nyc by train", "cities near nyc by train", "best hudson valley commuter
    towns", "does kingston ny have a train station" → a near-a-train ranking.
  - "downtown revitalization initiative" + town, "dri round 9", "ny forward" → a
    state-backed-downtowns ranking. The state's own pages list winners without context.
  - "upstate new york population", "upstate new york towns", "mohawk valley ny" → county
    and region pages with counts and dated figures.
  - "is kingston ny a safe place to live" is common and we have no crime data; the site
    does not answer it and must not pretend to.
- **inferred, from sampled result pages.** Page one for the "best towns" and "move to"
  queries is realtor blogs and listicles (travel and lifestyle magazines, agent sites,
  WorldAtlas, Niche), plus Zillow and Redfin market pages for town-level price queries.
  None cite a source file or a date; most are undated or 2023. A dated, sourced,
  per-town answer with a grade is a different kind of page, which is the opening. The
  same result pages show that "is X a good place to live" draws AI-overview-style answers
  built from Niche and Reddit; the counter is text that a model can quote verbatim with
  a date attached.

## What was changed on the site (this PR)

Everything is generated from the export, so it stays current with every publish.

- **Town pages.** Title `Catskill, NY: grade A, steady`; description opens with the
  question people type and answers it in figures. A "Is X, NY a good place to live or
  invest in?" section with one quotable paragraph built from the data
  (`townSummary` in `site/src/lib/seo.ts`) and a key-facts list where every figure
  carries its period and source. Breadcrumbs link the region and county pages.
- **Region pages** (`/region/hudson-valley` and two more): every town ranked, plus the
  cheapest, the closest to New York City, the ones near a train, and the rising ones; an
  intro paragraph with counts, extremes and the ACS period. **County pages**
  (`/county/greene-county`, 21 in all) with the county-level IRS migration figures.
- **Three rankings** shaped like the queries: most affordable, near a train to New York
  City, Downtown Revitalization Initiative and NY Forward winners. Ranking and region
  titles carry the publish year.
- **Structured data** on every page as one `@graph`: `WebSite`, `Organization`
  (independent, no listings, contact), `WebPage` with `dateModified`, `BreadcrumbList`;
  `Place`/`City` with the scores as `PropertyValue` on town pages, `ItemList` on rankings
  and region and county pages, `FAQPage` on About, a fuller `Dataset` on Methodology
  (`variableMeasured`, `temporalCoverage`, keywords, licence) for Google Dataset Search.
- **Answer engines.** `/llms.txt` (what the scores mean, how to cite, one dated line per
  page) and `/llms-full.txt` (every town's paragraph and facts). `robots.txt` is
  generated, allows every crawler, names the AI crawlers explicitly, keeps `/api/` and
  `/data/` out, and points at the sitemap. The sitemap carries `lastmod` from the export
  stamp. A `robots` meta with `max-snippet:-1` and `max-image-preview:large` on every
  page; the 404 is `noindex`. About has the seven questions people ask, as text and as
  schema, and a citation format.

llms.txt is not a ranking signal for Google (Google has said so); it is there for agents
and answer engines that read it, and it costs one build step.

## What is not done, and needs the owner

- **Search Console and Bing Webmaster Tools.** Verify the domain (a DNS TXT record or the
  HTML file in `site/public/`), submit `sitemap-index.xml`, and check the coverage report
  after the first crawl. Bing Webmaster also feeds Copilot and, with an API key, gives
  exact Bing volume for the keyword list above.
- **IndexNow** (Bing, Yandex, and others) could ping on every publish from `publish.yml`
  with a key file in `site/public/`; free, but it needs a key the owner generates.
- **Off-site mentions** are what AI answers and Google both weigh most: a Wikipedia
  external link where a town article cites a figure, a data-journalism mention, the
  dataset listed on data.world or Kaggle under CC BY 4.0, a post in the Hudson Valley and
  upstate subreddits where those questions are asked. None of this can be automated.
- **Self-hosted fonts** would remove two third-party connections per page; the site
  passes the other Core Web Vitals because it ships no content JavaScript.
