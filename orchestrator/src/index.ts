import { alert } from "./alert";
import type { Env } from "./env";
import { actionForCron, instanceId, issueTitle, okKey } from "./plan";

export { Pipeline } from "./pipeline-container";
export { RefreshWorkflow } from "./refresh-workflow";

export default {
  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    const at = new Date(controller.scheduledTime);
    const action = actionForCron(controller.cron);
    if (action.type === "ignore") {
      console.warn(`no action for cron "${controller.cron}"`);
      return;
    }
    if (action.type === "start") {
      const id = instanceId(action.kind, at);
      try {
        await env.REFRESH_WORKFLOW.create({ id, params: { kind: action.kind } });
        console.log(`started ${id}`);
      } catch (err) {
        // An existing id means this month's run is already going or done: the second cron slot is a no-op.
        console.log(`not started (${id} exists or could not be created): ${String(err).slice(0, 200)}`);
      }
      return;
    }
    // Watchdog (3rd of the month): no success marker for this month's refresh means open an issue.
    if (!(await env.STATE.get(okKey("monthly", at)))) {
      await alert(env, issueTitle("watchdog", "no successful monthly run"), `**refresh monthly** has no successful run recorded for ${at.toISOString().slice(0, 7)}. Check the Workflows dashboard for \`${instanceId("monthly", at)}\`, or start one: \`wrangler workflows trigger comebacktowns-refresh '{"kind":"monthly"}'\`.`);
    }
  },
} satisfies ExportedHandler<Env>;
