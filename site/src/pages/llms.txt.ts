/**
 * llms.txt (llmstxt.org): what the site is, how to cite it, and one dated line per page, so
 * an answer engine can find the right town page and quote it with its source and date.
 */
import type { APIRoute } from "astro";
import { meta, methodology, momentum, momentumLabels, scores, sources, towns } from "../lib/data";
import { population, score1 } from "../lib/format";
import { rankings } from "../lib/rankings";
import { countyNames, countyPath, origin, regionNames, regionPath, regionOf } from "../lib/seo";

export const GET: APIRoute = () => {
  const site = meta.site;
  const first = Object.values(scores)[0];
  const firstMo = Object.values(momentum)[0];
  const stamp = meta.generated_at.slice(0, 10);
  const lines: string[] = [
    `# ${site.SITE_NAME}`,
    "",
    `> ${site.TAGLINE} Readiness grades and momentum labels for ${meta.town_count} cities and villages in New York's ${regionNames.join(", ")}, computed from public data. Every figure on every page names the source file it came from and the date it was pulled. The dataset is CC BY 4.0.`,
    "",
    `Readiness (0 to 100, graded A to F within two population bands, split at ${methodology.grading.population_band_split.toLocaleString("en-US")}) asks whether the ingredients for a revival are present: ${methodology.factors.map((f) => `${f.name.replaceAll("_", " ")} (${Math.round(f.weight * 100)}%)`).join(", ")}. Momentum (0 to 100; rising at ${methodology.momentum.grading.bands.rising} and above, fading below ${methodology.momentum.grading.bands.steady}, 50 is keeping pace) asks whether anything is happening now: ${methodology.momentum.factors.map((f) => f.name).join(", ")}, each judged against a New York benchmark. A grade ranks a town against others of its size; a label is direction, not a forecast.`,
    "",
    `Versions: readiness ${first?.config_version ?? "n/a"} computed ${first?.computed_at.slice(0, 10) ?? "n/a"}; momentum ${firstMo?.config_version ?? "n/a"} computed ${firstMo?.computed_at.slice(0, 10) ?? "n/a"}; published ${stamp}. ${site.SITE_NAME} is independent: no municipality, developer or broker, and no listings. It is not financial, investment or relocation advice, the data is provided as is from public sources that can contain errors, the scores describe places, never who should live in them, and nothing on the site measures crime or safety (${origin}/about#not). Corrections: ${site.CONTACT_EMAIL}.`,
    "",
    `How to cite: "${site.SITE_NAME}, ${origin}/town/<slug>, readiness ${first?.config_version ?? "v1"} and momentum ${firstMo?.config_version ?? "v2"}, published ${stamp}." Each town page lists the exact snapshot key behind every figure.`,
    "",
    "## Start here",
    `- [Methodology](${origin}/methodology): weights, every curve, suppression rules, the dataset download`,
    `- [Rankings](${origin}/rankings): one question per list`,
    ...rankings.map((r) => `- [${r.title}](${origin}/rankings/${r.slug}): ${r.question}`),
    `- [All towns](${origin}/towns), [Compare](${origin}/compare), [Sources](${origin}/sources), [About](${origin}/about)`,
    "",
    "## Regions",
    ...regionNames.map((r) => `- [${r} towns](${origin}${regionPath(r)}): ${towns.filter((t) => t.region === r).length} cities and villages, ranked, with the cheapest, the closest to New York City and the ones near a train`),
    "",
    "## Counties",
    ...countyNames.map((c) => `- [${c} County](${origin}${countyPath(c)}): ${regionOf(c)}, ${towns.filter((t) => t.county === c).length} town${towns.filter((t) => t.county === c).length === 1 ? "" : "s"}`),
    "",
    "## Towns",
  ];
  for (const t of [...towns].sort((a, b) => a.name.localeCompare(b.name))) {
    const s = scores[t.geoid];
    const mo = momentum[t.geoid];
    const bits = [
      `${t.legal_type}, ${t.county} County, ${t.region}`,
      `pop. ${population(t.pop_latest)} (${t.pop_latest_year})`,
      s ? `readiness ${score1(s.readiness)}${s.grade ? ` (${s.grade})` : " (no grade)"}` : "not scored",
      mo ? `momentum ${score1(mo.momentum)} (${mo.label ? momentumLabels[mo.label].toLowerCase() : "no label"})` : "",
    ].filter(Boolean);
    lines.push(`- [${t.name}, NY](${origin}/town/${t.slug}): ${bits.join("; ")}`);
  }
  lines.push("", "## Data", `- [Dataset CSV](${origin}/downloads/comebacktowns-dataset.csv): one row per town, every metric with period and suppression flag, CC BY 4.0`, `- JSON API: ${origin}/api/search?q=, ${origin}/api/filter?momentum=rising&max_drive_nyc=120, ${origin}/api/compare?towns=a,b,c`, `- Sources: ${sources.map((s) => s.name).join("; ")}`, "", "## Optional", `- [llms-full.txt](${origin}/llms-full.txt): the full summary paragraph of every town, with its figures, periods and sources`, "");
  return new Response(lines.join("\n"), { headers: { "Content-Type": "text/plain; charset=utf-8" } });
};


