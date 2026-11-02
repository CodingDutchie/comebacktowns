import { Container } from "@cloudflare/containers";
import type { Env } from "./env";

/**
 * The Python pipeline image (container/Dockerfile). It serves a tiny job API on 8080
 * (container/server.py): POST /jobs starts one whitelisted job, GET /jobs/<id> reports it.
 * Polling keeps the instance awake; `sleepAfter` only reclaims it if the Workflow dies.
 */
export class Pipeline extends Container<Env> {
  defaultPort = 8080;
  sleepAfter = "20m";

  constructor(ctx: ConstructorParameters<typeof Container>[0], env: Env) {
    super(ctx, env);
    // Secrets reach the container as environment variables, exactly the names the pipeline reads.
    this.envVars = {
      CLOUDFLARE_API_TOKEN: env.CLOUDFLARE_API_TOKEN,
      CLOUDFLARE_ACCOUNT_ID: env.CLOUDFLARE_ACCOUNT_ID,
      CENSUS_API_KEY: env.CENSUS_API_KEY,
    };
  }
}
