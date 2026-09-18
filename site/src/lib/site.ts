import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

export interface SiteConfig {
  SITE_NAME: string;
  SITE_DOMAIN: string;
  CONTACT_EMAIL: string;
  TAGLINE: string;
  STATE_ABBR: string;
}

/** Brand strings from config/site.yml. Never hardcode these in templates. */
export const site: SiteConfig = parse(
  readFileSync(fileURLToPath(new URL("../../../config/site.yml", import.meta.url)), "utf8"),
);
