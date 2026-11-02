import type { Env } from "./env";
import { ISSUE_LABEL, scrub } from "./plan";

/**
 * Open (or comment on) a refresh-failure issue. Without GITHUB_TOKEN this only logs, and the
 * failed instance stays visible in the Workflows dashboard. Never throws: alerting must not
 * mask the failure it reports.
 */
export async function alert(env: Env, title: string, body: string): Promise<void> {
  const secrets = [env.CLOUDFLARE_API_TOKEN, env.CENSUS_API_KEY, env.GITHUB_TOKEN];
  const text = scrub(body, secrets).slice(0, 6000);
  console.error(`ALERT ${title}\n${text}`);
  if (!env.GITHUB_TOKEN) return;
  const api = `https://api.github.com/repos/${env.GITHUB_REPO}/issues`;
  const headers = {
    authorization: `Bearer ${env.GITHUB_TOKEN}`,
    accept: "application/vnd.github+json",
    "user-agent": "comebacktowns-refresh",
    "content-type": "application/json",
  };
  try {
    const list = await fetch(`${api}?state=open&labels=${ISSUE_LABEL}&per_page=50`, { headers });
    const open = list.ok ? ((await list.json()) as Array<{ number: number; title: string }>) : [];
    const existing = open.find((i) => i.title === title);
    if (existing) {
      await fetch(`${api}/${existing.number}/comments`, { method: "POST", headers, body: JSON.stringify({ body: `Failed again.\n\n${text}` }) });
    } else {
      await fetch(api, { method: "POST", headers, body: JSON.stringify({ title, body: text, labels: [ISSUE_LABEL] }) });
    }
  } catch (err) {
    console.error("could not open the issue:", scrub(String(err), secrets));
  }
}
