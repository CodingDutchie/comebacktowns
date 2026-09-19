import { methodology, type MetricEntry } from "./data";

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const oneDecimal = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

export function formatValue(name: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const fmt = methodology.metrics[name]?.format ?? "number";
  switch (fmt) {
    case "money":
      return money.format(value);
    case "percent":
      return `${oneDecimal.format(value * 100)}%`;
    case "change":
      return `${value > 0 ? "+" : ""}${oneDecimal.format(value * 100)}%`;
    case "per_1k_change":
      return `${value > 0 ? "+" : ""}${oneDecimal.format(value)} per 1,000`;
    case "minutes": {
      const m = Math.round(value);
      return m >= 60 ? (m % 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${Math.floor(m / 60)} h`) : `${m} min`;
    }
    case "miles":
      return `${oneDecimal.format(value)} mi`;
    case "per_1k":
      return `${oneDecimal.format(value)} per 1,000`;
    case "year":
      return String(Math.round(value));
    case "flag":
      return value >= 0.5 ? "Yes" : "No";
    default:
      return number.format(value);
  }
}

export function label(name: string): string {
  return methodology.metrics[name]?.label ?? name.replaceAll("_", " ");
}

export function describe(name: string): string {
  return methodology.metrics[name]?.description ?? "";
}

export function periodLabel(entry: MetricEntry | undefined): string {
  return entry?.period ?? "";
}

export function pct(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

export function score1(x: number | null | undefined): string {
  return x === null || x === undefined ? "—" : x.toFixed(1);
}

export function population(n: number | null): string {
  return n === null ? "—" : number.format(n);
}

import { factorLabels, methodology as m, momentumLabels, shortLabels, type MethodologyInput, type Momentum, type Score, type Town } from "./data";
import { bandRank, band as bandName } from "./data";

/** The scored (non-benchmark) momentum inputs a town has, over how many the config names. */
export function momentumUsage(mo: Momentum): { used: number; total: number } {
  const scored = m.momentum.factors.flatMap((f) => f.inputs.filter((i) => !i.context_only).map((i) => i.name));
  const used = scored.filter((name) => mo.inputs[name]?.status === "usable").length;
  return { used, total: scored.length };
}

function compact(name: string, value: number, score: Pick<Score, "inputs">, inputs: MethodologyInput[]): string {
  const short = shortLabels[name] ?? label(name).toLowerCase();
  if (name === "median_home_value") {
    const metro = score.inputs.metro_median_home_value?.value;
    return metro ? `price ${Math.round((value / metro) * 100)}% of metro` : `${short} ${formatValue(name, value)}`;
  }
  if (name === "dri_award_amount" && value === 0) return "no state award";
  const fmt = m.metrics[name]?.format;
  if (fmt === "flag") return `${short}: ${value >= 0.5 ? "yes" : "no"}`;
  const bench = inputs.find((i) => i.context_only && i.name === `${name}_ny_median`);
  const benchValue = bench ? score.inputs[bench.name]?.value : undefined;
  const vs = benchValue !== undefined && benchValue !== null ? ` vs NY ${formatValue(name, benchValue)}` : "";
  return `${short} ${formatValue(name, value)}${vs}`;
}

/** One line per factor: every usable input with its value, then how many are not. */
export function inputSummary(score: Pick<Score, "inputs">, inputs: MethodologyInput[]): string {
  const scored = inputs.filter((i) => !i.context_only);
  const parts: string[] = [];
  let missing = 0;
  for (const inp of scored) {
    const i = score.inputs[inp.name];
    if (i?.status === "usable" && i.value !== null) parts.push(compact(inp.name, i.value, score, inputs));
    else if (i?.status !== "not_applicable") missing += 1;
  }
  if (missing) parts.push(`${missing} not available`);
  return parts.join(" · ");
}

function joinNames(names: string[]): string {
  const labels = names.map((n) => (factorLabels[n] ?? n).toLowerCase());
  return labels.length <= 1 ? labels.join("") : `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}

/** Where the town sits in its band, and what carries or drags its readiness. */
export function readinessMeaning(score: Score, town: Town): string {
  const rank = bandRank(town);
  const where = rank ? `Ranks ${rank.position} of ${rank.size} among towns ${bandName(town)}.` : "";
  const entries = Object.entries(score.factor_scores).filter((e): e is [string, number] => e[1] !== null);
  if (!entries.length) return where;
  const sorted = [...entries].sort((a, b) => b[1] - a[1]);
  const strong = sorted.filter(([, v]) => v >= 0.6).slice(0, 2).map(([k]) => k);
  const weak = sorted.filter(([, v]) => v <= 0.35).slice(-2).reverse().map(([k]) => k);
  const bits: string[] = [];
  if (strong.length) bits.push(`strongest in ${joinNames(strong)}`);
  if (weak.length) bits.push(`weakest in ${joinNames(weak)}`);
  const sentence = bits.length ? `${bits.join("; ")}.` : "";
  return [where, sentence.charAt(0).toUpperCase() + sentence.slice(1)].filter(Boolean).join(" ");
}

/** Which momentum factors run ahead of or behind the benchmark, and which are not scored. */
export function momentumMeaning(mo: Momentum): string {
  const ahead: string[] = [];
  const behind: string[] = [];
  const unscored: string[] = [];
  for (const [k, v] of Object.entries(mo.factor_scores)) {
    if (v === null || v === undefined) unscored.push(k);
    else if (v >= 0.6) ahead.push(k);
    else if (v <= 0.4) behind.push(k);
  }
  const bits: string[] = [];
  if (ahead.length) bits.push(`ahead on ${joinNames(ahead)}`);
  if (behind.length) bits.push(`behind on ${joinNames(behind)}`);
  if (!ahead.length && !behind.length && unscored.length < Object.keys(mo.factor_scores).length) bits.push("keeping pace with the benchmarks");
  if (unscored.length) bits.push(`${joinNames(unscored)} not scored`);
  const usage = momentumUsage(mo);
  const tail = mo.label ? "" : ` Fewer than ${Math.ceil(m.momentum.min_coverage * usage.total)} of ${usage.total} inputs, so no label.`;
  const sentence = bits.join("; ");
  return `${sentence.charAt(0).toUpperCase()}${sentence.slice(1)}.${tail}`;
}

export function momentumLabel(mo: Momentum | undefined): string {
  return mo?.label ? (momentumLabels[mo.label] ?? mo.label) : "no label";
}
