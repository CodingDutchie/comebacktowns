// @ts-check
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

// Brand strings come from config/site.yml, the single source of truth.
const site = parse(readFileSync(fileURLToPath(new URL("../config/site.yml", import.meta.url)), "utf8"));

export default defineConfig({
  site: `https://${site.SITE_DOMAIN}`,
  output: "static",
  trailingSlash: "never",
  build: { format: "file" },
  integrations: [sitemap()],
});
