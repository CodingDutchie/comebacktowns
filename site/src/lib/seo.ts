/**
 * Search and answer-engine helpers: slugs for the region and county pages, the quotable
 * per-town sentences, and the JSON-LD building blocks. Every sentence here is built from
 * the data and names its period, so a search engine or a language model can quote it and
 * a reader can check it.
 */
import { bandRank, band, meta, metric, momentum, momentumLabels, scores, sourceShort, towns, usable, type MetricEntry, type Town } from "./data";
import { formatValue, momentumMeaning, population, readinessMeaning, score1 } from "./format";

export const origin = `https://${meta.site.SITE_DOMAIN}`;
export const year = meta.generated_at.slice(0, 4);

export function slugify(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}
export const regionSlug = (region: string) => slugify(region);
export const regionPath = (region: string) => `/region/${regionSlug(region)}`;
export const countySlug = (county: string) => `${slugify(county)}-county`;
export const countyPath = (county: string) => `/county/${countySlug(county)}`;

export const regionNames = [...new Set(towns.map((t) => t.region))].sort();
export const countyNames = [...new Set(towns.map((t) => t.county))].sort();
export const regionOf = (county: string) => towns.find((t) => t.county === county)!.region;

/** Towns ordered by readiness, unscored last, then by name. */
export function byReadiness(list: Town[]): Town[] {
  return [...list].sort((a, b) => (scores[b.geoid]?.readiness ?? -1) - (scores[a.geoid]?.readiness ?? -1) || a.name.localeCompare(b.name));
}

export interface Fact { name: string; label: string; value: string; period: string; source: string; }

/** The headline figures of a town, each with its period and source, in reading order. */
export function townFacts(town: Town): Fact[] {
  const names: [string, string][] = [
    ["median_home_value", "Median home value"],
    ["metro_median_home_value", "Metro median home value"],
    ["zhvi", "Zillow home value index"],
    ["zhvi_change_1y", "Zillow home value change, 1 year"],
    ["median_gross_rent", "Median gross rent"],
    ["median_household_income", "Median household income"],
    ["poverty_rate", "Poverty rate"],
    ["vacancy_rate", "Vacancy rate"],
    ["pre1940_share", "Homes built before 1940"],
    ["nrhp_district_count", "National Register historic districts"],
    ["drive_min_nyc", "Drive to New York City"],
    ["drive_min_regional_hub", "Drive to the nearest regional hub"],
    ["miles_to_rail_station", "Nearest Amtrak or Metro-North station"],
    ["drive_min_nearest_hospital", "Drive to the nearest hospital"],
    ["broadband_subscription_share", "Households with a wired broadband subscription"],
    ["under_18_share", "Residents under 18"],
    ["osm_business_count", "Storefront businesses mapped"],
    ["osm_business_per_1k", "Businesses per 1,000 residents"],
    ["permit_units", "Housing units permitted"],
    ["permits_per_1k", "Permits per 1,000 residents, 3-year mean"],
    ["dri_award_count", "Downtown Revitalization Initiative and NY Forward awards"],
    ["dri_award_amount", "Latest state downtown award"],
    ["county_net_migration_rate", "County net migration of tax filers, per 1,000"],
  ];
  const out: Fact[] = [];
  for (const [name, label] of names) {
    const e = metric(town.geoid, name);
    if (!usable(e)) continue;
    if (name === "dri_award_amount" && e.value === 0) continue;
    out.push({ name, label, value: formatValue(name, e.value), period: e.period, source: sourceShort(e.source_id) });
  }
  return out;
}

const val = (e: MetricEntry | undefined, name: string) => (usable(e) ? formatValue(name, e.value) : null);

/** The page title: name, grade and direction, within a search result's width. */
export function townTitle(town: Town): string {
  const s = scores[town.geoid];
  const mo = momentum[town.geoid];
  const gradeBit = s?.grade ? `grade ${s.grade}` : s ? `readiness ${Math.round(s.readiness)}` : "profile";
  const moBit = mo?.label ? `, ${mo.label}` : "";
  return `${town.name}, NY: ${gradeBit}${moBit}`;
}

/** The meta description: the question people type, then the figures that answer it. */
export function townDescription(town: Town): string {
  const s = scores[town.geoid];
  const mo = momentum[town.geoid];
  const m = (n: string) => metric(town.geoid, n);
  const change = val(m("population_change"), "population_change");
  const home = val(m("median_home_value"), "median_home_value");
  const nyc = val(m("drive_min_nyc"), "drive_min_nyc");
  const figures = [home ? `median home ${home}` : "", nyc ? `${nyc} to NYC` : ""].filter(Boolean);
  const bits = [
    `Is ${town.name}, NY a good place to live or invest in?`,
    `${cap(town.legal_type)} in ${town.county} County, pop. ${population(town.pop_latest)}${change ? ` (${change} since 2020)` : ""}.`,
    s ? `Readiness ${Math.round(s.readiness)}${s.grade ? ` (grade ${s.grade})` : ""}${mo?.label ? `, momentum ${mo.label}` : ""}.` : "",
    figures.length ? `${figures.join(", ")}.` : "",
    "Sourced, dated public data.",
  ].filter(Boolean);
  return bits.join(" ").replace(/\.\s+([a-z])/g, (_, c: string) => `. ${c.toUpperCase()}`);
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** One quotable paragraph per town: what it is, how it scores, and the figures behind that. */
export function townSummary(town: Town): string[] {
  const s = scores[town.geoid];
  const mo = momentum[town.geoid];
  const m = (n: string) => metric(town.geoid, n);
  const site = meta.site.SITE_NAME;
  const pop = m("population_change");
  const first = `${town.name} is a ${town.legal_type} in ${town.county} County, in New York's ${town.region}, with ${population(town.pop_latest)} residents in ${town.pop_latest_year}${usable(pop) ? `, ${formatValue("population_change", pop.value)} since 2020` : ""}.`;
  const rank = bandRank(town);
  const scoreLine = s
    ? `On ${site} it scores ${score1(s.readiness)} of 100 for readiness${s.grade ? `, grade ${s.grade}` : ", not graded because too few inputs exist"}${rank ? ` (rank ${rank.position} of ${rank.size} among towns ${band(town)})` : ""}${mo ? `, and ${score1(mo.momentum)} of 100 for momentum${mo.label ? `, labelled ${momentumLabels[mo.label].toLowerCase()}` : ", with no label because fewer than three of its four inputs exist"}` : ""}.`
    : `${site} has not scored ${town.name} yet.`;
  const why = [s ? readinessMeaning(s, town).replace(/^Ranks [^.]*\.\s*/, "") : "", mo ? `Momentum: ${lower(momentumMeaning(mo))}` : ""].filter(Boolean).join(" ");
  const home = m("median_home_value");
  const metro = m("metro_median_home_value");
  const nyc = m("drive_min_nyc");
  const rail = m("miles_to_rail_station");
  const figures: string[] = [];
  if (usable(home)) figures.push(`The median home was worth ${formatValue("median_home_value", home.value)} (${home.period}${usable(metro) ? `, ${Math.round((home.value / metro.value) * 100)}% of the metro median` : ""})`);
  if (usable(nyc)) figures.push(`${figures.length ? "and it" : "It"} is ${formatValue("drive_min_nyc", nyc.value)} by road from New York City${usable(rail) ? `, ${formatValue("miles_to_rail_station", rail.value)} from the nearest Amtrak or Metro-North station` : ""}`);
  const dri = m("dri_award_count");
  const amount = m("dri_award_amount");
  const award = usable(dri) && dri.value > 0 ? `The state has backed its downtown with ${dri.value === 1 ? "one" : dri.value} Downtown Revitalization Initiative or NY Forward award${dri.value === 1 ? "" : "s"}${usable(amount) && amount.value > 0 ? `, the latest ${formatValue("dri_award_amount", amount.value)}` : ""}.` : "";
  return [first, scoreLine, why, figures.length ? `${figures.join(", ")}.` : "", award].filter(Boolean);
}

const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);

/** JSON-LD blocks. `@context` is added once by the layout, which wraps these in a graph. */
export function breadcrumbs(items: { name: string; path: string }[]): Record<string, unknown> {
  return {
    "@type": "BreadcrumbList",
    itemListElement: items.map((it, i) => ({ "@type": "ListItem", position: i + 1, name: it.name, item: `${origin}${it.path}` })),
  };
}

export function itemList(name: string, list: { name: string; path: string }[], description?: string): Record<string, unknown> {
  return {
    "@type": "ItemList",
    name,
    ...(description ? { description } : {}),
    numberOfItems: list.length,
    itemListOrder: "https://schema.org/ItemListOrderDescending",
    itemListElement: list.map((it, i) => ({ "@type": "ListItem", position: i + 1, name: it.name, url: `${origin}${it.path}` })),
  };
}

export function placeLd(town: Town): Record<string, unknown> {
  const s = scores[town.geoid];
  const mo = momentum[town.geoid];
  const props: Record<string, unknown>[] = [];
  if (s) {
    props.push({ "@type": "PropertyValue", name: "Readiness score", value: Number(s.readiness.toFixed(1)), minValue: 0, maxValue: 100, description: `${meta.site.SITE_NAME} readiness ${s.config_version}, computed ${s.computed_at.slice(0, 10)}` });
    if (s.grade) props.push({ "@type": "PropertyValue", name: "Readiness grade", value: s.grade, description: `Percentile grade among towns ${band(town)}` });
  }
  if (mo) {
    props.push({ "@type": "PropertyValue", name: "Momentum score", value: Number(mo.momentum.toFixed(1)), minValue: 0, maxValue: 100, description: `${meta.site.SITE_NAME} momentum ${mo.config_version}, computed ${mo.computed_at.slice(0, 10)}; 50 is keeping pace` });
    if (mo.label) props.push({ "@type": "PropertyValue", name: "Momentum label", value: momentumLabels[mo.label] });
  }
  for (const f of townFacts(town).filter((f) => ["median_home_value", "median_gross_rent", "drive_min_nyc"].includes(f.name))) {
    const e = metric(town.geoid, f.name)!;
    props.push({ "@type": "PropertyValue", name: f.label, value: e.value, description: `${f.period}, ${f.source}` });
  }
  return {
    "@type": town.legal_type === "city" ? "City" : "Place",
    "@id": `${origin}/town/${town.slug}#place`,
    name: `${town.name}, New York`,
    alternateName: `${cap(town.legal_type)} of ${town.name}`,
    url: `${origin}/town/${town.slug}`,
    description: townSummary(town).slice(0, 2).join(" "),
    identifier: { "@type": "PropertyValue", propertyID: "GEOID", value: town.geoid },
    address: { "@type": "PostalAddress", addressLocality: town.name, addressRegion: "NY", addressCountry: "US" },
    geo: { "@type": "GeoCoordinates", latitude: town.lat, longitude: town.lon },
    containedInPlace: { "@type": "AdministrativeArea", name: `${town.county} County, New York`, url: `${origin}${countyPath(town.county)}` },
    additionalProperty: props,
  };
}

export function faq(items: { q: string; a: string }[]): Record<string, unknown> {
  return {
    "@type": "FAQPage",
    mainEntity: items.map((it) => ({ "@type": "Question", name: it.q, acceptedAnswer: { "@type": "Answer", text: it.a } })),
  };
}
