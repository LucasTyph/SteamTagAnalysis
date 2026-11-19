"""`stp export`: write the website's data files to web/public/data/.

- games.parquet      per-game fields for the explorer (relevant columns only)
- game_tags.parquet  (appid, tagid, rank) for relevant, non-excluded tags
- combos.parquet     precomputed pair/triple statistics
- tags.json          tag list with per-tag stats
- meta.json          build/analysis settings, fit stats and counts
- findings.json      numbers behind the Findings and Home pages
- timelines/index.json        one summary row per timeline game
- timelines/<appid>.json      monthly history, turning points, announcements (lazy-loaded)
- timelines/tag_curves.json   average trajectory by primary tag

Developer keys (studio groups, see build/studios.py) are replaced by small integer
IDs, so the browser can still cluster by developer for arbitrary combos without
shipping the keys; `group_devs` says how many developer accounts a group merges.
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
            SELECT dev_key, (ROW_NUMBER() OVER (ORDER BY dev_key))::INTEGER AS dev_id,
                   group_devs::SMALLINT AS group_devs
            FROM (
                SELECT dev_key, COUNT(DISTINCT COALESCE(dev_key_raw, dev_key)) AS group_devs
                FROM games WHERE review_count >= ? GROUP BY dev_key
            )
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
                   g.is_early_access, g.developer, d.dev_id, d.group_devs
            FROM games g JOIN game_scores s USING (appid) JOIN dev_ids d USING (dev_key)
            ORDER BY g.appid
            """,
            out_dir / "games.parquet",
        )
        _copy(
            con,
            """
            SELECT gt.appid::INTEGER AS appid, gt.tagid::INTEGER AS tagid, gt.rank::TINYINT AS rank
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
        _export_timelines(con, out_dir / "timelines")
        from pipeline.export import findings

        (out_dir / "findings.json").write_text(
            json.dumps(findings.compute(con), indent=1, default=str), "utf-8"
        )
    finally:
        con.close()
    return {p.name: p.stat().st_size for p in sorted(out_dir.iterdir())}


def _r(v, digits=1):
    return None if v is None else round(float(v), digits)


def _export_timelines(con, out: Path, max_news: int = 15) -> None:
    has = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'timeline_games'"
    ).fetchone()[0]
    if not has:
        return
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()

    index = []
    rows = con.execute(
        """
        SELECT tg.appid, g.name, g.developer, tg.first_month, tg.last_month, tg.total_reviews,
               tg.overall_score, tg.launch_score, tg.recent_score, tg.drift, tg.trough_score,
               tg.trough_month, tg.peak_score, tg.recovery, tg.decline, tg.volatility,
               tg.n_changes,
               (SELECT list(t.name ORDER BY gt.rank)[1:3] FROM game_tags gt
                JOIN tag_stats t USING (tagid) WHERE gt.appid = tg.appid AND gt.relevant) AS tags
        FROM timeline_games tg JOIN games g USING (appid)
        ORDER BY tg.total_reviews DESC, tg.appid
        """
    ).fetchall()
    for r in rows:
        index.append(
            {
                "appid": r[0],
                "name": r[1],
                "developer": r[2],
                "first": r[3].isoformat()[:7],
                "last": r[4].isoformat()[:7],
                "reviews": r[5],
                "overall": _r(r[6]),
                "launch": _r(r[7]),
                "recent": _r(r[8]),
                "drift": _r(r[9]),
                "trough": _r(r[10]),
                "trough_month": r[11].isoformat()[:7] if r[11] else None,
                "peak": _r(r[12]),
                "recovery": _r(r[13]),
                "decline": _r(r[14]),
                "volatility": _r(r[15]),
                "changes": r[16],
                "tags": list(r[17] or []),
            }
        )
    # Column-oriented: field names once, then one array per game (about half the size).
    cols = list(index[0]) if index else []
    compact = {"cols": cols, "rows": [[g[c] for c in cols] for g in index]}
    (out / "index.json").write_text(json.dumps(compact, separators=(",", ":")), "utf-8")

    monthly: dict[int, list] = {}
    for appid, month, up, down in con.execute(
        "SELECT appid, month, up, down FROM review_monthly ORDER BY appid, month"
    ).fetchall():
        monthly.setdefault(appid, []).append([month.isoformat()[:7], up, down])
    changes: dict[int, list] = {}
    for r in con.execute(
        "SELECT appid, month, before, after, news_title, news_url, news_date, news_kind "
        "FROM timeline_changes ORDER BY appid, month"
    ).fetchall():
        changes.setdefault(r[0], []).append(
            {
                "month": r[1].isoformat()[:7],
                "before": _r(r[2]),
                "after": _r(r[3]),
                "news": None
                if r[4] is None
                else {"title": r[4], "url": r[5], "date": r[6].date().isoformat(), "kind": r[7]},
            }
        )
    news: dict[int, list] = {}
    for appid, when, title, url, kind in con.execute(
        "SELECT appid, date, title, url, kind FROM news "
        "WHERE kind IN ('update', 'launch') ORDER BY appid, date DESC"
    ).fetchall():
        items = news.setdefault(appid, [])
        if len(items) < max_news:
            items.append(
                {"date": when.date().isoformat(), "title": title, "url": url, "kind": kind}
            )
    for game in index:
        a = game["appid"]
        # Always keep announcements matched to a turning point, even if older.
        kept = news.get(a, [])
        urls = {n["url"] for n in kept}
        for c in changes.get(a, []):
            if c["news"] and c["news"]["url"] not in urls:
                kept.append({k: c["news"][k] for k in ("date", "title", "url", "kind")})
                urls.add(c["news"]["url"])
        news[a] = kept
        doc = {
            "appid": a,
            "months": monthly.get(a, []),
            "changes": changes.get(a, []),
            "news": sorted(news.get(a, []), key=lambda n: n["date"]),
        }
        (out / f"{a}.json").write_text(json.dumps(doc, separators=(",", ":")), "utf-8")

    curves: dict[int, dict] = {}
    for tagid, name, m, n, mean, p25, p75 in con.execute(
        """
        SELECT c.tagid, t.name, c.months_since_launch, c.n_games, c.mean_pct, c.p25, c.p75
        FROM tag_curves c JOIN tags t USING (tagid) ORDER BY c.tagid, c.months_since_launch
        """
    ).fetchall():
        cur = curves.setdefault(tagid, {"tagid": tagid, "name": name, "points": []})
        cur["points"].append([m, n, _r(mean), _r(p25), _r(p75)])
    (out / "tag_curves.json").write_text(
        json.dumps(list(curves.values()), separators=(",", ":")), "utf-8"
    )
