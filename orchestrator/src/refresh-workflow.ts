/**
 * The refresh Workflow: the plan from plan.ts, one durable step per stage. A stage is either a
 * container job (started, then polled to completion inside the step) or the OSM Workflow in the
 * site Worker. Nothing is substituted or skipped: a failed stage stops the run, opens an issue,
 * and the later stages (load, publish) never happen, exactly like the GitHub workflows did.
 */
import { NonRetryableError } from "cloudflare:workflows";
import { WorkflowEntrypoint, type WorkflowEvent, type WorkflowStep } from "cloudflare:workers";
import { alert } from "./alert";
import type { Env, RefreshParams } from "./env";
import { buildPlan, issueTitle, okKey, parseDiscovered, scrub, type JobStatus, type Stage } from "./plan";

const POLL_MS = 15_000;
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function runJob(env: Env, stage: Extract<Stage, { type: "job" }>): Promise<JobStatus> {
  const box = env.PIPELINE.getByName("pipeline");
  const started = await box.fetch("http://container/jobs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ job: stage.job, params: stage.params }),
  });
  // 409 = a job is already running (a retried step re-attaching): follow it instead of starting another.
  if (started.status !== 202 && started.status !== 409) {
    throw new NonRetryableError(`container refused ${stage.job}: HTTP ${started.status} ${(await started.text()).slice(0, 300)}`);
  }
  const { id } = (await started.json()) as { id: string };
  const deadline = Date.now() + stage.timeoutMinutes * 60_000;
  while (Date.now() < deadline) {
    await sleep(POLL_MS);
    const res = await box.fetch(`http://container/jobs/${id}`);
    if (!res.ok) throw new Error(`job status HTTP ${res.status}`);
    const status = (await res.json()) as JobStatus;
    if (status.state === "running") continue;
    if (status.state === "failed") {
      // Not retried by the engine: the pipeline's own exit code is the verdict (QA stops are real stops).
      throw new NonRetryableError(`${stage.id} exited ${status.exit_code}\n${status.log_tail}`);
    }
    return status;
  }
  throw new Error(`${stage.id} still running after ${stage.timeoutMinutes} minutes`);
}

/** Start the OSM Workflow and wait. Any outcome but success is a warning: the Python ingest after it fills gaps. */
async function runOsmWorkflow(env: Env, stage: Extract<Stage, { type: "osm-workflow" }>): Promise<{ status: string }> {
  const asOf = new Date().toISOString().slice(0, 10);
  const instance = await env.OSM_WORKFLOW.create({ params: { as_of: asOf } });
  const deadline = Date.now() + stage.timeoutMinutes * 60_000;
  let last = "queued";
  while (Date.now() < deadline) {
    await sleep(POLL_MS * 4);
    last = (await instance.status()).status;
    if (last === "complete" || last === "errored" || last === "terminated") break;
  }
  if (last !== "complete") console.warn(`OSM Workflow ended as "${last}"; the Python ingest will fill the gaps`);
  return { status: last };
}

export class RefreshWorkflow extends WorkflowEntrypoint<Env, RefreshParams> {
  async run(event: WorkflowEvent<RefreshParams>, step: WorkflowStep): Promise<{ stages: string[] }> {
    const { kind, skip_pilot } = event.payload;
    const done: string[] = [];
    let stageName = "start";
    try {
      let plan: Stage[];
      if (kind === "discover") {
        stageName = "discover";
        const found = await step.do(
          "discover newer years",
          { retries: { limit: 1, delay: "1 minute" }, timeout: "15 minutes" },
          async () => parseDiscovered((await runJob(this.env, { type: "job", id: "discover", job: "discover", params: {}, timeoutMinutes: 10, retries: 1 })).stdout),
        );
        if (!found.length) return { stages: ["discover: nothing new"] };
        plan = buildPlan({ kind, sources: found, skipPilot: skip_pilot });
      } else {
        plan = buildPlan({ kind, skipPilot: skip_pilot });
      }
      for (const stage of plan) {
        stageName = stage.id;
        const config = { retries: { limit: stage.type === "job" ? stage.retries : 0, delay: "2 minutes" as const, backoff: "exponential" as const }, timeout: `${stage.timeoutMinutes + 5} minutes` as `${number} minutes` };
        await step.do(stage.id, config, async () => (stage.type === "job" ? (await runJob(this.env, stage), { ok: true }) : runOsmWorkflow(this.env, stage)));
        done.push(stage.id);
      }
      await step.do("record success", async () => {
        await this.env.STATE.put(okKey(kind, event.timestamp), new Date().toISOString());
      });
      return { stages: done };
    } catch (err) {
      const secrets = [this.env.CLOUDFLARE_API_TOKEN, this.env.CENSUS_API_KEY, this.env.GITHUB_TOKEN];
      const message = scrub(err instanceof Error ? err.message : String(err), secrets);
      await alert(this.env, issueTitle(kind, stageName), `The **${kind}** refresh stopped at \`${stageName}\` and published nothing.\n\nInstance: \`${event.instanceId}\`\n\n\`\`\`\n${message}\n\`\`\`\n\nEvery stage resumes where it left off, so re-running after the cause is fixed is safe: \`wrangler workflows trigger comebacktowns-refresh '{"kind":"${kind}"}'\`.`);
      throw err;
    }
  }
}
