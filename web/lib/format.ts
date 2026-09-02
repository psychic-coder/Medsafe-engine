import type { PairStatus, ResolutionStatus } from "./types";

const rupees = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** PMBJP prices are Indian retail prices, so they are formatted as rupees. */
export function formatPrice(value: number): string {
  return rupees.format(value);
}

export function formatPercent(value: number): string {
  return `${value.toFixed(value % 1 === 0 ? 0 : 1)}%`;
}

export function formatScore(value: number): string {
  return value.toFixed(1);
}

/** Human-readable strength, e.g. "500 mg". */
export function formatStrength(
  value: number | null,
  unit: string | null,
): string | null {
  if (value === null) return null;
  const trimmed = Number.isInteger(value) ? String(value) : String(value);
  return unit ? `${trimmed} ${unit}` : trimmed;
}

export const PRODUCT_SOURCE_LABEL: Record<string, string> = {
  PMBJP: "Janaushadhi",
  branded_csv: "Branded",
};

export const RESOLUTION_LABEL: Record<ResolutionStatus, string> = {
  resolved: "Identified",
  combination: "Identified — combination pack",
  needs_review: "Not certain",
  unresolved: "Not found",
};

export const PAIR_LABEL: Record<PairStatus, string> = {
  interaction: "Known interaction",
  no_known_interaction: "Checked, nothing found",
  not_checked: "Not checked",
};

/** Severity strings arrive from DDInter as free text; normalise for display and styling. */
export function severityRank(severity: string | null): "major" | "moderate" | "minor" | "unknown" {
  const value = (severity ?? "").trim().toLowerCase();
  if (value.includes("major") || value.includes("severe")) return "major";
  if (value.includes("moderate")) return "moderate";
  if (value.includes("minor")) return "minor";
  return "unknown";
}
