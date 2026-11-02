import type { Pipeline } from "./pipeline-container";

export interface Env {
  PIPELINE: DurableObjectNamespace<Pipeline>;
  REFRESH_WORKFLOW: Workflow;
  OSM_WORKFLOW: Workflow;
  STATE: KVNamespace;
  GITHUB_REPO: string;
  CLOUDFLARE_API_TOKEN: string;
  CLOUDFLARE_ACCOUNT_ID: string;
  CENSUS_API_KEY: string;
  /** Optional: issues:write on GITHUB_REPO, so a failure opens a refresh-failure issue. */
  GITHUB_TOKEN?: string;
}

export interface RefreshParams {
  kind: "monthly" | "annual" | "discover";
  skip_pilot?: boolean;
}
