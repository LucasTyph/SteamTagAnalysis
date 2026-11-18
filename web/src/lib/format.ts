export const fmtInt = (n: number | null | undefined) =>
  n == null ? "–" : n.toLocaleString("en-US");

export const fmtPct = (n: number | null | undefined, digits = 1) =>
  n == null || !Number.isFinite(n) ? "–" : `${n.toFixed(digits)}%`;

/** Signed percentage points, e.g. "+4.2 pp". */
export const fmtPp = (n: number | null | undefined, digits = 1) =>
  n == null || !Number.isFinite(n) ? "–" : `${n > 0 ? "+" : n < 0 ? "−" : "±"}${Math.abs(n).toFixed(digits)} pp`;

export const steamUrl = (appid: number) => `https://store.steampowered.com/app/${appid}`;

/** "positive" | "negative" | "neutral", based on whether the CI excludes zero. */
export function effectTone(low: number | undefined, high: number | undefined): string {
  if (low == null || high == null) return "neutral";
  if (low > 0) return "positive";
  if (high < 0) return "negative";
  return "neutral";
}
