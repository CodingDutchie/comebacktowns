/** llms-full.txt: every town's quotable summary and dated key facts, in one file. */
import type { APIRoute } from "astro";
import { meta, towns } from "../lib/data";
import { origin, townFacts, townSummary } from "../lib/seo";

export const GET: APIRoute = () => {
  const lines: string[] = [`# ${meta.site.SITE_NAME}: every town`, "", `Published ${meta.generated_at.slice(0, 10)}. See ${origin}/llms.txt for what the scores mean and how to cite. Each section is one town page; the facts carry their period and source.`, ""];
  for (const t of [...towns].sort((a, b) => a.name.localeCompare(b.name))) {
    lines.push(`## ${t.name}, NY`, `${origin}/town/${t.slug}`, "", townSummary(t).join(" "), "");
    for (const f of townFacts(t)) lines.push(`- ${f.label}: ${f.value} (${f.period}, ${f.source})`);
    lines.push("");
  }
  return new Response(lines.join("\n"), { headers: { "Content-Type": "text/plain; charset=utf-8" } });
};
