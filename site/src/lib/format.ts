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
      return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`;
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
