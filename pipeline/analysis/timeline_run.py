"""Timeline analysis over every game in `review_monthly` (part of `stp analyze`).

Writes:
- timeline_games    one row of summary metrics per game
- timeline_changes  turning points with their matched announcement
- tag_curves        average monthly % by months since launch, per primary tag
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from pipeline.analysis.timelines import (
    REVIEWS_START,
    TIMELINES,
    NewsItem,
    TimelineConfig,
    match_news,
    summarize,
)
from pipeline.config import ANALYSIS, ANALYSIS_DB_PATH, AnalysisConfig


def run(
    path: Path = ANALYSIS_DB_PATH,
    cfg: TimelineConfig = TIMELINES,
    analysis_cfg: AnalysisConfig = ANALYSIS,
    log=print,
) -> dict[str, int]:
    import duckdb
    import pyarrow as pa

    con = duckdb.connect(str(path))
    try:
        rows = con.execute(
            "SELECT appid, month, up, down FROM review_monthly ORDER BY appid, month"
        ).fetchall()
        if not rows:
            log("timelines: no review history fetched yet (stp fetch timelines)")
            return {"games": 0}
        series: dict[int, tuple[list, list, list]] = defaultdict(lambda: ([], [], []))
        for appid, month, up, down in rows:
            s = series[appid]
            s[0].append(month)
            s[1].append(up)
            s[2].append(down)

        news: dict[int, list[NewsItem]] = defaultdict(list)
        for appid, when, title, url, kind in con.execute(
            "SELECT appid, date, title, url, kind FROM news"
        ).fetchall():
            news[appid].append(NewsItem(when, title, url, kind))

        released = dict(
            con.execute(
                "SELECT appid, first_release::DATE FROM games "
                "WHERE appid IN (SELECT DISTINCT appid FROM review_monthly)"
            ).fetchall()
        )

        games, changes = [], []
        for appid, (months, up, down) in series.items():
            if sum(up) + sum(down) == 0:
                continue
            rel = released.get(appid)
            pre = (rel is not None and rel < REVIEWS_START) or months[0] <= REVIEWS_START
            s = summarize(months, up, down, cfg, launched_before_reviews=pre)
            games.append(
                {
                    "appid": appid,
                    "first_month": s.first_month,
                    "last_month": s.last_month,
                    "months": s.months,
                    "total_reviews": s.total_reviews,
                    "overall_score": s.overall_score,
                    "launch_score": s.launch_score,
                    "recent_score": s.recent_score,
                    "drift": s.drift,
                    "trough_score": s.trough_score,
                    "trough_month": s.trough_month,
                    "peak_score": s.peak_score,
                    "peak_month": s.peak_month,
                    "recovery": s.recovery,
                    "decline": s.decline,
                    "volatility": s.volatility,
                    "n_changes": len(s.changes),
                }
            )
            for c in s.changes:
                item = match_news(c.month, news.get(appid, []), cfg.news_window_days)
                changes.append(
                    {
                        "appid": appid,
                        "month": c.month,
                        "before": c.before,
                        "after": c.after,
                        "shift": c.shift,
                        "news_title": item.title if item else None,
                        "news_url": item.url if item else None,
                        "news_date": item.date if item else None,
                        "news_kind": item.kind if item else None,
                    }
                )

        games_tbl = pa.Table.from_pylist(games)  # noqa: F841 — referenced in SQL
        changes_schema = pa.schema(
            [
                ("appid", pa.int64()),
                ("month", pa.date32()),
                ("before", pa.float64()),
                ("after", pa.float64()),
                ("shift", pa.float64()),
                ("news_title", pa.string()),
                ("news_url", pa.string()),
                ("news_date", pa.timestamp("s")),
                ("news_kind", pa.string()),
            ]
        )
        changes_tbl = pa.Table.from_pylist(changes, schema=changes_schema)  # noqa: F841
        con.execute("CREATE OR REPLACE TABLE timeline_games AS SELECT * FROM games_tbl")
        con.execute("CREATE OR REPLACE TABLE timeline_changes AS SELECT * FROM changes_tbl")

        # Average trajectory by primary tag (a game's top relevant tag), months since launch.
        con.execute(
            """
            CREATE OR REPLACE TABLE tag_curves AS
            WITH primary_tag AS (
                SELECT gt.appid, arg_min(gt.tagid, gt.rank) AS tagid
                FROM game_tags gt JOIN tags t USING (tagid)
                WHERE gt.relevant AND NOT list_contains($excluded, t.name)
                  AND gt.appid IN (SELECT appid FROM timeline_games)
                GROUP BY gt.appid
            ),
            monthly AS (
                SELECT r.appid, p.tagid,
                       datediff('month', tg.first_month, r.month) AS m,
                       100.0 * r.up / (r.up + r.down) AS pct
                FROM review_monthly r
                JOIN timeline_games tg USING (appid) JOIN primary_tag p USING (appid)
                WHERE r.up + r.down >= $min_reviews
            ),
            eligible AS (
                SELECT tagid FROM primary_tag GROUP BY tagid HAVING COUNT(*) >= $min_games
            )
            SELECT tagid, m AS months_since_launch, COUNT(*) AS n_games,
                   AVG(pct) AS mean_pct, quantile_cont(pct, 0.25) AS p25,
                   quantile_cont(pct, 0.75) AS p75
            FROM monthly WHERE tagid IN (SELECT tagid FROM eligible) AND m <= 96
            GROUP BY tagid, m HAVING COUNT(*) >= 5
            ORDER BY tagid, m
            """,
            {
                "excluded": list(analysis_cfg.excluded_tags),
                "min_reviews": cfg.min_month_reviews,
                "min_games": 8,
            },
        )
        n_tags = con.execute("SELECT COUNT(DISTINCT tagid) FROM tag_curves").fetchone()[0]
        matched = sum(1 for c in changes if c["news_title"])
        log(
            f"timelines: {len(games):,} games, {len(changes):,} turning points "
            f"({matched:,} matched to an announcement), {n_tags} tag curves"
        )
        return {"games": len(games), "changes": len(changes), "tag_curves": n_tags}
    finally:
        con.close()
