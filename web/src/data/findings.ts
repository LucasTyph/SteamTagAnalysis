import { dataUrl } from "./url";

export interface ComboFinding {
  tags: string[];
  n_games: number;
  n_devs: number;
  score: number;
  predicted: number;
  effect: number;
  ci_low: number;
  ci_high: number;
}

export interface TagFinding {
  name: string;
  n_games: number;
  n_devs: number;
  mean_score: number;
  coef: number;
}

export interface Findings {
  year_trend: { year: number; games: number; score: number }[];
  size_buckets: { label: string; games: number; score: number }[];
  tags_best: TagFinding[];
  tags_worst: TagFinding[];
  pairs_best: ComboFinding[];
  pairs_worst: ComboFinding[];
  drift?: { n: number; median_drift: number; pct_up5: number; pct_down5: number };
  comebacks?: { appid: number; name: string; trough: number; recent: number; trough_month: string }[];
  turning_points?: { n: number; pct_unmatched: number };
  bomb_clusters?: {
    month: string;
    n: number;
    avg_shift: number;
    games: string[];
    top_publisher: string | null;
    top_publisher_games: number;
  }[];
  tag_aging?: { name: string; n: number; early: number; later: number; change: number }[];
  excluded_tags: string[];
}

let promise: Promise<Findings> | null = null;
export function loadFindings(): Promise<Findings> {
  promise ??= fetch(dataUrl("findings.json")).then((r) => r.json());
  return promise;
}

export const REPO_URL = "https://github.com/LucasTyph/Game-Data";
