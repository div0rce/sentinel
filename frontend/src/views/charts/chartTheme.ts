/**
 * Shared Recharts styling derived from the design-system tokens.
 *
 * Colors are `var(--token)` strings rather than resolved hex, so charts re-theme
 * live when the dark/light toggle flips the `data-theme` attribute — the same
 * mechanism every other surface uses. Only fills/axes/tooltip change; the data and
 * chart semantics are identical to the backend feeds.
 */

export const ACCENT = "var(--accent)";
export const SUCCESS = "var(--success)";
export const WARN = "var(--warn)";
export const DANGER = "var(--danger)";

export const GRID_STROKE = "var(--line)";
export const AXIS_STROKE = "var(--line-strong)";

export const AXIS_TICK = {
  fill: "var(--fg-muted)",
  fontSize: 11,
  fontFamily: "var(--font-mono)",
} as const;

export const TOOLTIP_CONTENT_STYLE = {
  background: "var(--navy-800)",
  border: "1px solid var(--line)",
  borderRadius: "2px",
  fontFamily: "var(--font-mono)",
  fontSize: 12,
} as const;

export const TOOLTIP_ITEM_STYLE = { color: "var(--fg)" } as const;
export const TOOLTIP_LABEL_STYLE = { color: "var(--fg-muted)" } as const;
export const TOOLTIP_CURSOR = { fill: "var(--navy-700)", opacity: 0.4 } as const;

/** Confidence buckets: deep-red below 0.6, amber to 0.8, green above. Keyed off the
 *  bucket's lower bound so it works for any number of bins the backend returns. */
export function confidenceColor(lower: number): string {
  if (lower < 0.6) return DANGER;
  if (lower < 0.8) return WARN;
  return SUCCESS;
}

/** SLA age buckets ("<1h", "1–4h", "4–24h", ">24h"): over-threshold is danger,
 *  the 4–24h band is the warn zone, younger items are healthy. Matched without the
 *  en-dash so the literal stays ASCII. */
export function slaColor(label: string): string {
  if (label.startsWith(">")) return DANGER;
  if (label.includes("24")) return WARN;
  return SUCCESS;
}
