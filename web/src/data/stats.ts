// Small statistics helpers matching the pipeline (pipeline/analysis/combos.py).

// Two-sided 90% t critical values for df = 1..30; normal approximation beyond.
const T90 = [
  6.314, 2.92, 2.353, 2.132, 2.015, 1.943, 1.895, 1.86, 1.833, 1.812, 1.796, 1.782, 1.771, 1.761,
  1.753, 1.746, 1.74, 1.734, 1.729, 1.725, 1.721, 1.717, 1.714, 1.711, 1.708, 1.706, 1.703, 1.701,
  1.699, 1.697,
];

export function tCritical90(df: number): number {
  if (df < 1) return Number.NaN;
  if (df <= 30) return T90[Math.floor(df) - 1];
  return 1.645 + 1.6 / df; // close to the t quantile for large df
}

export interface Interval {
  low: number;
  high: number;
}

export function ci90(mean: number, sd: number | null, n: number): Interval | null {
  if (sd == null || !Number.isFinite(sd) || n < 2) return null;
  const half = (tCritical90(n - 1) * sd) / Math.sqrt(n);
  return { low: mean - half, high: mean + half };
}
