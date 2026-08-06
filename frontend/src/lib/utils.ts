import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Format a number with monospace tabular alignment (e.g. $1,234.56). */
export function fmtMoney(n: number | null | undefined, currency = "USD"): string {
  if (n == null || isNaN(n as number)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency, maximumFractionDigits: 2,
  }).format(n);
}

export function fmtNum(n: number | null | undefined, decimals = 0): string {
  if (n == null || isNaN(n as number)) return "—";
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  }).format(n);
}

export function fmtPercent(n: number | null | undefined, decimals = 2): string {
  if (n == null || isNaN(n as number)) return "—";
  return `${(n * 100).toFixed(decimals)}%`;
}

export function fmtDate(iso: string | undefined | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "2-digit" });
}
