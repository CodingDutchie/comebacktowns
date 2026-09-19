/**
 * robots.txt: every crawler may read every page, and the answer-engine crawlers are named
 * so the allowance is explicit. The JSON API and the compare data file are not pages.
 */
import type { APIRoute } from "astro";
import { origin } from "../lib/seo";

const AI_BOTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User", "anthropic-ai", "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot", "Applebot-Extended", "Bingbot", "DuckAssistBot", "CCBot", "Amazonbot", "meta-externalagent", "YouBot", "cohere-ai", "MistralAI-User"];

export const GET: APIRoute = () => {
  const lines = ["User-agent: *", "Allow: /", "Disallow: /api/", "Disallow: /data/", ""];
  for (const bot of AI_BOTS) lines.push(`User-agent: ${bot}`, "Allow: /", "Disallow: /api/", "");
  lines.push(`Sitemap: ${origin}/sitemap-index.xml`, `# Machine-readable summary: ${origin}/llms.txt`, "");
  return new Response(lines.join("\n"), { headers: { "Content-Type": "text/plain; charset=utf-8" } });
};
