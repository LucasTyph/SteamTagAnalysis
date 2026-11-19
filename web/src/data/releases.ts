// New Releases data (web/public/data/releases/), generated at deploy time from the
// tracking-data branch by `stp track export`.
import { dataUrl } from "./url";

export interface ReleasesMeta {
  generated_at: string;
  tracking_since: string | null;
  last_run: string | null;
  data_through: string | null;
  tracked: number;
  with_reviews: number;
  clean: number;
  early_access: number;
  listed_games: number;
  min_reviews_listed: number;
  releases_per_day: [string, number][];
}

export interface ReleaseGame {
  appid: number;
  name: string;
  release: string;
  ea: boolean;
  tag: string | null;
  reviews: number;
  pct: number | null;
  d7_reviews: number | null;
  d7_pct: number | null;
  clean: boolean;
}

export interface Mover extends ReleaseGame {
  change: number;
}

export type CurvePoint = [day: number, n: number, p25: number, median: number, p75: number];

export interface Settle {
  from_day: number;
  to_day: number;
  n: number;
  p25?: number;
  median?: number;
  p75?: number;
  pct_moved_5?: number;
  pct_up_5?: number;
  pct_down_5?: number;
  changes?: number[];
}

export interface TagSpeed {
  tag: string;
  n: number;
  median: number;
  mean: number;
  pct_10plus: number;
}

export interface Aggregates {
  curve_all: CurvePoint[];
  curve_early_access: CurvePoint[];
  curve_full_launch: CurvePoint[];
  settle: Settle[];
  speed_by_tag: TagSpeed[];
  risers: Mover[];
  fallers: Mover[];
}

export interface GameDays {
  appid: number;
  release: string;
  days: [offset: number, up: number, down: number][];
}

async function getJson<T>(file: string): Promise<T | null> {
  const res = await fetch(dataUrl(`releases/${file}`));
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to load ${file} (${res.status})`);
  // Vite's dev server answers unknown paths with index.html; treat that as missing.
  if (!(res.headers.get("content-type") ?? "").includes("json")) return null;
  return res.json();
}

export interface ReleasesData {
  meta: ReleasesMeta;
  games: ReleaseGame[];
  aggregates: Aggregates;
}

let promise: Promise<ReleasesData | null> | null = null;
export function loadReleases(): Promise<ReleasesData | null> {
  promise ??= Promise.all([
    getJson<ReleasesMeta>("meta.json"),
    getJson<ReleaseGame[]>("games.json"),
    getJson<Aggregates>("aggregates.json"),
  ]).then(([meta, games, aggregates]) => (meta && games && aggregates ? { meta, games, aggregates } : null));
  return promise;
}

const gameCache = new Map<number, Promise<GameDays | null>>();
export function loadGameDays(appid: number): Promise<GameDays | null> {
  let p = gameCache.get(appid);
  if (!p) {
    p = getJson<GameDays>(`g/${Math.trunc(appid)}.json`);
    gameCache.set(appid, p);
  }
  return p;
}

/** Daily rows → one point per day since release with cumulative % positive. */
export function cumulativeSeries(g: GameDays, lastDay: number) {
  const byDay = new Map(g.days.map(([d, up, down]) => [d, [up, down]]));
  const out: { day: number; up: number; down: number; cumUp: number; cumN: number; pct: number | null }[] = [];
  let cu = 0;
  let cn = 0;
  for (let d = 0; d <= lastDay; d++) {
    const [up, down] = byDay.get(d) ?? [0, 0];
    cu += up;
    cn += up + down;
    out.push({ day: d, up, down, cumUp: cu, cumN: cn, pct: cn >= 10 ? (100 * cu) / cn : null });
  }
  return out;
}
