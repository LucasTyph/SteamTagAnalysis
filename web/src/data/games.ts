// Per-game lookups over the exported tables (games, game_tags, combos) in DuckDB-WASM.
import { query } from "./db";

export interface GameHit {
  appid: number;
  name: string;
  year: number | null;
  review_count: number;
  pct_positive: number;
}

export interface GameDetail extends GameHit {
  score: number;
  predicted: number;
  resid: number;
  price_usd: number | null;
  is_free: boolean;
  is_early_access: boolean;
  developer: string | null;
  dev_id: number;
  /** Share of all games scoring below this one, 0–100. */
  score_pctile: number;
  /** Share of all games beating their prediction by less than this one, 0–100. */
  resid_pctile: number;
  dev_games: number;
  /** Developer accounts merged into this game's studio group (1 = not grouped). */
  group_devs: number;
  tagids: number[]; // relevant tags, by vote rank
}

export interface GameCombo {
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
}

export interface SimilarGame extends GameHit {
  shared: number;
  score: number;
  resid: number;
}

/** SQL string literal: the only user text that reaches SQL is the search box. */
const lit = (s: string) => `'${s.replace(/'/g, "''")}'`;
const int = (n: number) => String(Math.trunc(Number(n)));

const HIT_COLS = `appid, name, year::INTEGER AS year, review_count, pct_positive::INTEGER AS pct_positive`;

export function normalizeQuery(text: string): string {
  return text.trim().toLowerCase().normalize("NFKD").replace(/\p{M}/gu, "");
}

/** Name search: prefix matches first, then by review count. */
export async function searchGames(text: string, limit = 8): Promise<GameHit[]> {
  const q = normalizeQuery(text);
  if (!q) return [];
  return query<GameHit>(`
    WITH g AS (SELECT *, strip_accents(lower(name)) AS key FROM games)
    SELECT ${HIT_COLS} FROM g
    WHERE contains(key, ${lit(q)})
    ORDER BY starts_with(key, ${lit(q)}) DESC, review_count DESC
    LIMIT ${int(limit)}`);
}

export async function gameDetail(appid: number): Promise<GameDetail | null> {
  const rows = await query<Omit<GameDetail, "tagids"> & { tagids: number[] | null }>(`
    WITH ranked AS (
      SELECT *, 100 * percent_rank() OVER (ORDER BY score) AS score_pctile,
             100 * percent_rank() OVER (ORDER BY resid) AS resid_pctile,
             COUNT(*) OVER (PARTITION BY dev_id) AS dev_games
      FROM games
    )
    SELECT ${HIT_COLS}, score::DOUBLE AS score, predicted::DOUBLE AS predicted,
           resid::DOUBLE AS resid, price_usd::DOUBLE AS price_usd, is_free, is_early_access,
           developer, dev_id, score_pctile::DOUBLE AS score_pctile,
           resid_pctile::DOUBLE AS resid_pctile, dev_games::INTEGER AS dev_games,
           group_devs::INTEGER AS group_devs,
           (SELECT list(tagid ORDER BY rank) FROM game_tags t WHERE t.appid = ranked.appid) AS tagids
    FROM ranked WHERE appid = ${int(appid)}`);
  if (!rows.length) return null;
  const r = rows[0];
  // Arrow lists come back as typed vectors; copy into a plain array.
  return { ...r, tagids: r.tagids ? Array.from(r.tagids, Number) : [] };
}

/** Every precomputed pair and triple made only of the game's tags (synonym pairs dropped). */
export async function gameCombos(tagids: number[]): Promise<GameCombo[]> {
  if (tagids.length < 2) return [];
  const set = tagids.map(int).join(",");
  return query<GameCombo>(`
    SELECT size::INTEGER AS size, t1, t2, t3, n_games, n_devs,
           mean_score::DOUBLE AS mean_score, mean_predicted::DOUBLE AS mean_predicted,
           effect::DOUBLE AS effect, ci_low::DOUBLE AS ci_low, ci_high::DOUBLE AS ci_high,
           q_value::DOUBLE AS q_value
    FROM combos
    WHERE NOT has_synonym AND t1 IN (${set}) AND t2 IN (${set}) AND (t3 IS NULL OR t3 IN (${set}))
    ORDER BY effect DESC`);
}

/**
 * Games from other developers with the closest tag profile (cosine similarity, tags
 * weighted by vote rank), taking the 40 closest and showing the most-reviewed of those.
 */
export async function similarGames(appid: number, devId: number, limit = 8): Promise<SimilarGame[]> {
  return query<SimilarGame>(`
    WITH w AS (SELECT appid, tagid, (11 - rank)::DOUBLE AS w FROM game_tags),
    mine AS (SELECT tagid, w FROM w WHERE appid = ${int(appid)}),
    norms AS (SELECT appid, sqrt(SUM(w * w)) AS n FROM w GROUP BY appid),
    sim AS (
      SELECT w.appid, SUM(w.w * mine.w) AS dot, COUNT(*)::INTEGER AS shared
      FROM w JOIN mine USING (tagid) WHERE w.appid <> ${int(appid)} GROUP BY w.appid
    ),
    closest AS (
      SELECT g.*, shared, dot / (n * (SELECT sqrt(SUM(w * w)) FROM mine)) AS cos
      FROM sim JOIN norms USING (appid) JOIN games g USING (appid)
      WHERE g.dev_id <> ${int(devId)}
      ORDER BY cos DESC, review_count DESC LIMIT 40
    )
    SELECT ${HIT_COLS}, shared, score::DOUBLE AS score, resid::DOUBLE AS resid
    FROM closest ORDER BY review_count DESC LIMIT ${int(limit)}`);
}

export type Board = "over" | "under";

/** Well-reviewed games that beat (or miss) what their tags predict by the most. */
export async function standouts(board: Board, minReviews = 5000, limit = 12): Promise<(GameHit & { resid: number; score: number })[]> {
  return query(`
    SELECT ${HIT_COLS}, resid::DOUBLE AS resid, score::DOUBLE AS score FROM games
    WHERE review_count >= ${int(minReviews)}
    ORDER BY resid ${board === "over" ? "DESC" : "ASC"} LIMIT ${int(limit)}`);
}

// --- helpers ------------------------------------------------------------------------

const logit = (p: number) => Math.log(p / (1 - p));
const expit = (x: number) => 1 / (1 + Math.exp(-x));

/**
 * How much a tag moves a prediction that starts at `predictedPct`, in points: the
 * prediction minus what it would be without that tag (the model is additive on the
 * logit scale, so the same tag moves a 95% game less than a 75% one).
 */
export function tagPull(predictedPct: number, coef: number | null): number | null {
  if (coef == null) return null;
  const p = Math.min(Math.max(predictedPct / 100, 1e-4), 1 - 1e-4);
  return 100 * (p - expit(logit(p) - coef));
}
