"""Numbers behind the website's Findings and Home pages (findings.json).

Computed from the analysis tables at export time, so the written findings never
drift from the data. The page supplies the wording; this supplies the numbers.
"""

from __future__ import annotations

from pipeline.config import ANALYSIS


def _rows(con, sql: str, params=None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def _r(v, digits=1):
    return None if v is None else round(float(v), digits)


def compute(con) -> dict:
    out: dict = {}

    out["year_trend"] = [
        {"year": r["year"], "games": r["n"], "score": _r(r["score"])}
        for r in _rows(
            con,
            """
            SELECT year(g.first_release) AS year, COUNT(*) AS n, AVG(s.score) AS score
            FROM games g JOIN game_scores s USING (appid)
            WHERE year(g.first_release) BETWEEN 2010 AND 2026
            GROUP BY 1 ORDER BY 1
            """,
        )
    ]

    out["size_buckets"] = [
        {"label": r["label"], "games": r["n"], "score": _r(r["score"])}
        for r in _rows(
            con,
            """
            SELECT CASE WHEN review_count < 100 THEN '20–99'
                        WHEN review_count < 1000 THEN '100–999'
                        WHEN review_count < 10000 THEN '1k–10k'
                        ELSE '10k+' END AS label,
                   MIN(review_count) AS lo, COUNT(*) AS n, AVG(s.score) AS score
            FROM games g JOIN game_scores s USING (appid)
            GROUP BY 1 ORDER BY lo
            """,
        )
    ]

    tag_cols = "name, n_games, n_devs, mean_score, coef"
    out["tags_best"] = [
        {**r, "mean_score": _r(r["mean_score"]), "coef": _r(r["coef"], 3)}
        for r in _rows(
            con,
            f"SELECT {tag_cols} FROM tag_stats WHERE n_devs >= 100 ORDER BY coef DESC LIMIT 6",
        )
    ]
    out["tags_worst"] = [
        {**r, "mean_score": _r(r["mean_score"]), "coef": _r(r["coef"], 3)}
        for r in _rows(
            con, f"SELECT {tag_cols} FROM tag_stats WHERE n_devs >= 100 ORDER BY coef LIMIT 6"
        )
    ]

    combo_sql = """
        SELECT list_filter([t1n.name, t2n.name, t3n.name], lambda x: x IS NOT NULL) AS tags,
               c.n_games, c.n_devs, c.mean_score, c.mean_predicted, c.effect, c.ci_low, c.ci_high
        FROM combos c
        JOIN tags t1n ON t1n.tagid = c.t1 JOIN tags t2n ON t2n.tagid = c.t2
        LEFT JOIN tags t3n ON t3n.tagid = c.t3
        WHERE c.size = 2 AND NOT c.has_synonym AND c.q_value < 0.1 AND c.n_devs >= 15
        ORDER BY {order} LIMIT 6
    """

    def combo(r):
        return {
            "tags": list(r["tags"]),
            "n_games": r["n_games"],
            "n_devs": r["n_devs"],
            "score": _r(r["mean_score"]),
            "predicted": _r(r["mean_predicted"]),
            "effect": _r(r["effect"]),
            "ci_low": _r(r["ci_low"]),
            "ci_high": _r(r["ci_high"]),
        }

    out["pairs_best"] = [combo(r) for r in _rows(con, combo_sql.format(order="c.ci_low DESC"))]
    out["pairs_worst"] = [combo(r) for r in _rows(con, combo_sql.format(order="c.ci_high ASC"))]

    if con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'timeline_games'"
    ).fetchone()[0]:
        d = _rows(
            con,
            """
            SELECT COUNT(*) AS n, median(drift) AS median_drift,
                   AVG((drift > 5)::INT) * 100 AS pct_up5, AVG((drift < -5)::INT) * 100 AS pct_down5
            FROM timeline_games WHERE drift IS NOT NULL
            """,
        )[0]
        out["drift"] = {k: _r(v) if k != "n" else v for k, v in d.items()}

        out["comebacks"] = [
            {**r, "trough": _r(r["trough"]), "recent": _r(r["recent"])}
            for r in _rows(
                con,
                """
                SELECT tg.appid, g.name, tg.trough_score AS trough, tg.recent_score AS recent,
                       strftime(tg.trough_month, '%Y-%m') AS trough_month
                FROM timeline_games tg JOIN games g USING (appid)
                WHERE tg.recovery IS NOT NULL ORDER BY tg.recovery DESC LIMIT 6
                """,
            )
        ]

        m = _rows(
            con,
            """
            SELECT COUNT(*) AS n, AVG((news_title IS NULL)::INT) * 100 AS pct_unmatched
            FROM timeline_changes
            """,
        )[0]
        out["turning_points"] = {"n": m["n"], "pct_unmatched": _r(m["pct_unmatched"])}

        clusters = _rows(
            con,
            """
            WITH big AS (
                SELECT tc.*, g.name, g.publisher FROM timeline_changes tc
                JOIN games g USING (appid) WHERE tc.shift <= -25
            )
            SELECT strftime(month, '%Y-%m') AS month, COUNT(*) AS n, AVG(shift) AS avg_shift,
                   list(name ORDER BY shift)[1:8] AS games,
                   mode(publisher) AS top_publisher
            FROM big GROUP BY month HAVING COUNT(*) >= 4 ORDER BY n DESC LIMIT 4
            """,
        )
        for c in clusters:
            c["avg_shift"] = _r(c["avg_shift"])
            c["games"] = list(c["games"])
            c["top_publisher_games"] = con.execute(
                """
                SELECT COUNT(*) FROM timeline_changes tc JOIN games g USING (appid)
                WHERE strftime(tc.month, '%Y-%m') = ? AND tc.shift <= -25 AND g.publisher = ?
                """,
                [c["month"], c["top_publisher"]],
            ).fetchone()[0]
        out["bomb_clusters"] = clusters

        out["tag_aging"] = [
            {**r, "early": _r(r["early"]), "later": _r(r["later"]), "change": _r(r["change"])}
            for r in _rows(
                con,
                """
                WITH a AS (
                    SELECT t.name,
                           AVG(mean_pct) FILTER (WHERE months_since_launch <= 6) AS early,
                           AVG(mean_pct) FILTER (
                               WHERE months_since_launch BETWEEN 36 AND 48) AS later,
                           MAX(n_games) AS n
                    FROM tag_curves c JOIN tags t USING (tagid) GROUP BY t.name
                )
                SELECT name, n, early, later, later - early AS change
                FROM a WHERE later IS NOT NULL AND n >= 8 ORDER BY change DESC
                """,
            )
        ]

    out["excluded_tags"] = list(ANALYSIS.excluded_tags)
    return out
