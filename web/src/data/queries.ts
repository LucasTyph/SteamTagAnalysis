// Typed queries over the exported data. Every statistic is developer-clustered
// like the pipeline: a developer's games are averaged first, then the stats are
// computed across developers.
import { dataUrl, query } from "./db";
import { ci90, type Interval } from "./stats";

export interface Tag {
  tagid: number;
  name: string;
  n_games: number;
  n_devs: number;
  mean_score: number;
  coef: number | null;
}

export interface Meta {
  build: Record<string, unknown>;
  analysis: Record<string, number | string>;
  excluded_tags: string[];
  counts: Record<string, number>;
}

export interface Filters {
  yearFrom: number | null;
  yearTo: number | null;
  price: "any" | "free" | "paid";
  earlyAccess: "any" | "exclude" | "only";
  minReviews: number;
}

export const DEFAULT_FILTERS: Filters = {
  yearFrom: null,
  yearTo: null,
  price: "any",
  earlyAccess: "any",
  minReviews: 20,
};

export interface ComboStats {
  n_games: number;
  n_devs: number;
  score: number | null;
  predicted: number | null;
  effect: number | null;
  ci: Interval | null;
}

export interface Companion extends ComboStats {
  tagid: number;
}

export interface GameRow {
  appid: number;
  name: string;
  year: number | null;
  review_count: number;
  pct_positive: number;
  score: number;
  predicted: number;
  resid: number;
  developer: string | null;
}

export interface PrecomputedCombo {
  size: number;
  t1: number;
  t2: number;
  t3: number | null;
  n_games: number;
  n_devs: number;
  mean_score: number;
  mean_predicted: number;
  effect: number;
  ci_low: number;
  ci_high: number;
  q_value: number;
  has_synonym: boolean;
  median_year: number | null;
}

// --- static JSON ---------------------------------------------------------------

let tagsPromise: Promise<Tag[]> | null = null;
export function loadTags(): Promise<Tag[]> {
  tagsPromise ??= fetch(dataUrl("tags.json")).then((r) => r.json());
  return tagsPromise;
}

let metaPromise: Promise<Meta> | null = null;
export function loadMeta(): Promise<Meta> {
  metaPromise ??= fetch(dataUrl("meta.json")).then((r) => r.json());
  return metaPromise;
}

// --- SQL building ----------------------------------------------------------------

function ids(tagIds: number[]): string {
  // Tag IDs come from our own tags.json; still force them to integers before inlining.
  return tagIds.map((t) => String(Math.trunc(Number(t)))).join(",");
}

function filterSql(f: Filters): string {
  const parts = [`g.review_count >= ${Math.trunc(f.minReviews)}`];
  if (f.yearFrom != null) parts.push(`g.year >= ${Math.trunc(f.yearFrom)}`);
  if (f.yearTo != null) parts.push(`g.year <= ${Math.trunc(f.yearTo)}`);
  if (f.price === "free") parts.push("g.is_free");
  if (f.price === "paid") parts.push("NOT g.is_free");
  if (f.earlyAccess === "exclude") parts.push("NOT g.is_early_access");
  if (f.earlyAccess === "only") parts.push("g.is_early_access");
  return parts.join(" AND ");
}

function matchingGames(tagIds: number[], f: Filters): string {
  const tagFilter = tagIds.length
    ? `JOIN (SELECT appid FROM game_tags WHERE tagid IN (${ids(tagIds)})
             GROUP BY appid HAVING COUNT(*) = ${tagIds.length}) m USING (appid)`
    : "";
  return `SELECT g.* FROM games g ${tagFilter} WHERE ${filterSql(f)}`;
}

const DEV_STATS = `
  SUM(n)::INTEGER AS n_games, COUNT(*)::INTEGER AS n_devs,
  AVG(s)::DOUBLE AS score, AVG(p)::DOUBLE AS predicted,
  AVG(r)::DOUBLE AS effect, STDDEV_SAMP(r)::DOUBLE AS sd`;

interface RawStats {
  n_games: number;
  n_devs: number;
  score: number | null;
  predicted: number | null;
  effect: number | null;
  sd: number | null;
}

function withCi<T extends RawStats>(r: T): Omit<T, "sd"> & { ci: Interval | null } {
  const { sd, ...rest } = r;
  return { ...rest, ci: r.effect == null ? null : ci90(r.effect, sd, r.n_devs) };
}

// --- queries -----------------------------------------------------------------------

export async function comboStats(tagIds: number[], f: Filters): Promise<ComboStats> {
  const [row] = await query<RawStats>(`
    WITH g AS (${matchingGames(tagIds, f)}),
    per_dev AS (
      SELECT dev_id, COUNT(*) AS n, AVG(score) AS s, AVG(predicted) AS p, AVG(resid) AS r
      FROM g GROUP BY dev_id
    )
    SELECT ${DEV_STATS} FROM per_dev`);
  return withCi({ ...row, n_games: row.n_games ?? 0 });
}

/** Stats for the current combo plus each other tag, for tags with enough developers. */
export async function companions(
  tagIds: number[],
  f: Filters,
  minDevs = 5,
): Promise<Companion[]> {
  const exclude = tagIds.length ? `WHERE gt.tagid NOT IN (${ids(tagIds)})` : "";
  const rows = await query<RawStats & { tagid: number }>(`
    WITH g AS (${matchingGames(tagIds, f)}),
    per_dev AS (
      SELECT gt.tagid, g.dev_id, COUNT(*) AS n, AVG(g.score) AS s,
             AVG(g.predicted) AS p, AVG(g.resid) AS r
      FROM g JOIN game_tags gt USING (appid) ${exclude}
      GROUP BY gt.tagid, g.dev_id
    )
    SELECT tagid, ${DEV_STATS} FROM per_dev
    GROUP BY tagid HAVING COUNT(*) >= ${Math.trunc(minDevs)}`);
  return rows.map(withCi);
}

export async function gamesIn(tagIds: number[], f: Filters, limit = 50): Promise<GameRow[]> {
  return query<GameRow>(`
    SELECT g.appid, g.name, g.year::INTEGER AS year, g.review_count,
           g.pct_positive::INTEGER AS pct_positive, g.score::DOUBLE AS score,
           g.predicted::DOUBLE AS predicted, g.resid::DOUBLE AS resid, g.developer
    FROM (${matchingGames(tagIds, f)}) g
    ORDER BY g.review_count DESC LIMIT ${Math.trunc(limit)}`);
}

export interface GemQuery {
  sizes: number[];
  direction: "best" | "worst";
  maxDevs: number;
  minScore: number;
  includeTag: number | null;
  limit: number;
}

export async function rankedCombos(q: GemQuery): Promise<PrecomputedCombo[]> {
  const where = [
    "NOT has_synonym",
    "q_value < 0.1",
    `size IN (${q.sizes.map((s) => Math.trunc(s)).join(",") || "2"})`,
    `n_devs <= ${Math.trunc(q.maxDevs)}`,
    q.direction === "best" ? "ci_low > 0" : "ci_high < 0",
    q.direction === "best" ? `mean_score >= ${Number(q.minScore)}` : "TRUE",
  ];
  if (q.includeTag != null) {
    const t = Math.trunc(q.includeTag);
    where.push(`(t1 = ${t} OR t2 = ${t} OR t3 = ${t})`);
  }
  return query<PrecomputedCombo>(`
    SELECT size::INTEGER AS size, t1, t2, t3, n_games, n_devs,
           mean_score::DOUBLE AS mean_score, mean_predicted::DOUBLE AS mean_predicted,
           effect::DOUBLE AS effect, ci_low::DOUBLE AS ci_low, ci_high::DOUBLE AS ci_high,
           q_value::DOUBLE AS q_value, has_synonym, median_year::INTEGER AS median_year
    FROM combos WHERE ${where.join(" AND ")}
    ORDER BY ${q.direction === "best" ? "ci_low DESC" : "ci_high ASC"}
    LIMIT ${Math.trunc(q.limit)}`);
}

export interface PairEdge {
  t1: number;
  t2: number;
  n_games: number;
  effect: number;
}

/** Pair co-occurrence among the given tags, for the network view. */
export async function pairEdges(tagIds: number[]): Promise<PairEdge[]> {
  const list = ids(tagIds);
  return query<PairEdge>(`
    SELECT t1, t2, n_games, effect::DOUBLE AS effect FROM combos
    WHERE size = 2 AND t1 IN (${list}) AND t2 IN (${list})`);
}
