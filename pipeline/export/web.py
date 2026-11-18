"""`stp export`: write the website's data files to web/public/data/.

- games.parquet      per-game fields for the explorer (relevant columns only)
- game_tags.parquet  (appid, tagid) for relevant, non-excluded tags
- combos.parquet     precomputed pair/triple statistics
- tags.json          tag list with per-tag stats
- meta.json          build/analysis settings, fit stats and counts

Developer keys are replaced by small integer IDs, so the browser can still
cluster by developer for arbitrary combos without shipping the keys.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.config import ANALYSIS, ANALYSIS_DB_PATH, BUILD, ROOT

WEB_DATA_DIR = ROOT / "web" / "public" / "data"


def _copy(con, sql: str, path: Path) -> None:
    con.execute(f"COPY ({sql}) TO '{path.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")


def run(db_path: Path = ANALYSIS_DB_PATH, out_dir: Path = WEB_DATA_DIR) -> dict[str, int]:
    import duckdb

    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        con.execute(
            """
            CREATE TEMP TABLE dev_ids AS
            SELECT dev_key, (ROW_NUMBER() OVER (ORDER BY dev_key))::INTEGER AS dev_id
            FROM (SELECT DISTINCT dev_key FROM games WHERE review_count >= ?)
            """,
            [BUILD.min_reviews],
        )
        _copy(
            con,
            """
            SELECT g.appid::INTEGER AS appid, g.name, year(g.first_release)::SMALLINT AS year,
                   g.review_count::INTEGER AS review_count, g.pct_positive::TINYINT AS pct_positive,
                   round(s.score, 2)::FLOAT AS score, round(s.predicted, 2)::FLOAT AS predicted,
                   round(s.resid, 2)::FLOAT AS resid, g.price_usd::FLOAT AS price_usd, g.is_free,
                   g.is_early_access, g.developer, d.dev_id
            FROM games g JOIN game_scores s USING (appid) JOIN dev_ids d USING (dev_key)
            ORDER BY g.appid
            """,
            out_dir / "games.parquet",
        )
        _copy(
            con,
            """
            SELECT gt.appid::INTEGER AS appid, gt.tagid::INTEGER AS tagid
            FROM game_tags gt JOIN game_scores USING (appid) JOIN tag_stats USING (tagid)
            WHERE gt.relevant ORDER BY gt.appid, gt.rank
            """,
            out_dir / "game_tags.parquet",
        )
        _copy(
            con,
            """
            SELECT size::TINYINT AS size, t1::INTEGER AS t1, t2::INTEGER AS t2,
                   t3::INTEGER AS t3, n_games::INTEGER AS n_games, n_devs::INTEGER AS n_devs,
                   round(mean_score, 2)::FLOAT AS mean_score,
                   round(mean_predicted, 2)::FLOAT AS mean_predicted,
                   round(effect, 2)::FLOAT AS effect, round(ci_low, 2)::FLOAT AS ci_low,
                   round(ci_high, 2)::FLOAT AS ci_high, q_value::FLOAT AS q_value,
                   round(naive_lift, 2)::FLOAT AS naive_lift, has_synonym,
                   median_reviews::INTEGER AS median_reviews, median_year::SMALLINT AS median_year
            FROM combos ORDER BY size, t1, t2, t3
            """,
            out_dir / "combos.parquet",
        )
        tags = [
            {
                "tagid": int(r[0]),
                "name": r[1],
                "n_games": int(r[2]),
                "n_devs": int(r[3]),
                "mean_score": round(r[4], 2),
                "coef": round(r[5], 4) if r[5] is not None else None,
            }
            for r in con.execute(
                "SELECT tagid, name, n_games, n_devs, mean_score, coef FROM tag_stats "
                "ORDER BY n_games DESC"
            ).fetchall()
        ]
        (out_dir / "tags.json").write_text(json.dumps(tags, separators=(",", ":")), "utf-8")

        def one(table: str) -> dict:
            cur = con.execute(f"SELECT * FROM {table}")
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, cur.fetchone(), strict=True))

        counts = {
            "games": con.execute("SELECT COUNT(*) FROM game_scores").fetchone()[0],
            "developers": con.execute("SELECT COUNT(*) FROM dev_ids").fetchone()[0],
            "tags": len(tags),
            "pairs": con.execute("SELECT COUNT(*) FROM combos WHERE size = 2").fetchone()[0],
            "triples": con.execute("SELECT COUNT(*) FROM combos WHERE size = 3").fetchone()[0],
        }
        meta = {
            "build": one("build_info"),
            "analysis": one("analysis_info"),
            "excluded_tags": list(ANALYSIS.excluded_tags),
            "counts": counts,
        }
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str), "utf-8")
    finally:
        con.close()
    return {p.name: p.stat().st_size for p in sorted(out_dir.iterdir())}
