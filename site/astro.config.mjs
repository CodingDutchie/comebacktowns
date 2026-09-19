// @ts-check
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

// Brand strings come from config/site.yml, the single source of truth.
const site = parse(readFileSync(fileURLToPath(new URL("../config/site.yml", import.meta.url)), "utf8"));

/** The export stamp from data/meta.json (or the sample fixture), ISO date. */
function lastmod() {
  for (const dir of ["./data/meta.json", "./sample-data/meta.json"]) {
    try {
      return JSON.parse(readFileSync(fileURLToPath(new URL(dir, import.meta.url)), "utf8")).generated_at;
    } catch {
      /* try the next */
    }
  }
  return new Date().toISOString();
}

export default defineConfig({
  site: `https://${site.SITE_DOMAIN}`,
  output: "static",
  trailingSlash: "never",
  build: { format: "file" },
  integrations: [
    sitemap({
      // Every page is rebuilt from the same export, so its stamp is the honest lastmod.
      serialize: (item) => ({ ...item, lastmod: lastmod() }),
      filter: (page) => !page.endsWith("/404"),
    }),
  ],
});
