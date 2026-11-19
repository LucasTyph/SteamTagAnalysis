"""`stp analyze`: game scores → baseline model → combo statistics.

Reads the tables from `stp build` and writes these to the same DuckDB file:
- game_scores    appid, score, predicted, resid (all in percentage points)
- tag_stats      per-tag game count, mean score, model coefficient
- combos         pair and triple statistics (see combos.py)
- synonym_pairs  near-synonym tag pairs
- analysis_info  prior, model fit and settings used
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from pipeline.analysis import combos, leaveout, model, shrinkage
from pipeline.config import ANALYSIS, ANALYSIS_DB_PATH, BUILD, AnalysisConfig, BuildConfig


def run(
    path: Path = ANALYSIS_DB_PATH,
    cfg: AnalysisConfig = ANALYSIS,
    build_cfg: BuildConfig = BUILD,
    log=print,
) -> dict:
    import duckdb
    import pyarrow as pa

    con = duckdb.connect(str(path))
    try:
        excluded = list(cfg.excluded_tags)
        games = con.execute(
            """
            SELECT appid, n_pos, review_count, year(first_release) AS year, price_usd,
                   is_free, is_early_access, dev_key
            FROM games WHERE review_count >= ? ORDER BY appid
            """,
            [build_cfg.min_reviews],
        ).fetchnumpy()
        n_games = len(games["appid"])
        log(f"games: {n_games:,}")

        # 1. Empirical-Bayes scores
        prior = shrinkage.fit_prior(games["n_pos"], games["review_count"])
        score = shrinkage.posterior_mean(games["n_pos"], games["review_count"], prior)
        log(f"prior: mean {prior.mean:.3f}, strength {prior.strength:.1f} pseudo-reviews")

        # 2. Baseline model
        gt = con.execute(
            """
            SELECT gt.appid, gt.tagid FROM game_tags gt
            JOIN games g USING (appid) JOIN tags t USING (tagid)
            WHERE gt.relevant AND g.review_count >= ? AND NOT list_contains(?, t.name)
            """,
            [build_cfg.min_reviews, excluded],
        ).fetchnumpy()
        tagids = np.unique(gt["tagid"])
        row_of = {a: i for i, a in enumerate(games["appid"])}
        col_of = {t: j for j, t in enumerate(tagids)}
        gi = np.fromiter((row_of[a] for a in gt["appid"]), int, len(gt["appid"]))
        ti = np.fromiter((col_of[t] for t in gt["tagid"]), int, len(gt["tagid"]))

        def as_float(a):
            return np.ma.filled(np.ma.asarray(a, dtype=float), np.nan)

        X, names = model.design_matrix(
            (gi, ti),
            tagids,
            n_games,
            year=as_float(games["year"]),
            price=as_float(games["price_usd"]),
            is_free=np.asarray(games["is_free"], bool),
            early_access=np.asarray(games["is_early_access"], bool),
            review_count=np.asarray(games["review_count"]),
        )
        fit = model.fit(X, score, tagids, names)
        log(f"model: ridge alpha {fit.alpha}, R² {fit.r2:.3f} (5-fold CV {fit.cv_r2:.3f})")
        y = model.logit(score)
        base = leaveout.Baseline.fit(X, y, fit.alpha)

        scores = pa.table(  # noqa: F841 — referenced in SQL
            {
                "appid": games["appid"],
                "score": score * 100,
                "predicted": fit.predicted * 100,
                "resid": (score - fit.predicted) * 100,
            }
        )
        con.execute("CREATE OR REPLACE TABLE game_scores AS SELECT * FROM scores")
        coefs = pa.table(  # noqa: F841
            {"tagid": list(fit.tag_coef), "coef": list(fit.tag_coef.values())}
        )
        con.execute(
            """
            CREATE OR REPLACE TEMP TABLE rel AS
            SELECT gt.appid, gt.tagid, s.score, s.predicted, s.resid,
                   g.review_count, year(g.first_release) AS year, g.dev_key
            FROM game_tags gt
            JOIN games g USING (appid) JOIN game_scores s USING (appid)
            JOIN tags t USING (tagid)
            WHERE gt.relevant AND NOT list_contains($excluded, t.name)
            """,
            {"excluded": excluded},
        )
        con.execute(
            """
            CREATE OR REPLACE TABLE tag_stats AS
            SELECT r.tagid, t.name, COUNT(*) AS n_games, COUNT(DISTINCT r.dev_key) AS n_devs,
                   AVG(r.score) AS mean_score,
                   AVG(r.resid) AS mean_resid, c.coef
            FROM rel r JOIN tags t USING (tagid) LEFT JOIN coefs c USING (tagid)
            GROUP BY ALL ORDER BY n_games DESC
            """
        )

        # 3. Synonyms and combos
        con.execute(
            "CREATE OR REPLACE TABLE synonym_pairs AS " + combos.SYNONYM_SQL,
            {"threshold": cfg.synonym_threshold},
        )
        frames = []
        for sql in (combos.PAIR_SQL, combos.TRIPLE_SQL):
            frames.append(
                con.sql(
                    sql, params={"min_support": cfg.min_support, "min_devs": cfg.min_devs}
                ).to_arrow_table()
            )
        raw = pa.concat_tables(frames)
        raw = raw.append_column("cid", pa.array(np.arange(raw.num_rows)))
        # Each mix against a baseline fitted without its own games (see leaveout.py).
        cand = raw.select(["cid", "size", "t1", "t2", "t3"])  # noqa: F841
        members = con.sql(combos.MEMBERS_SQL).fetchnumpy()
        rows = np.searchsorted(games["appid"], members["appid"])
        assert (games["appid"][rows] == members["appid"]).all(), "mix game not analysed"
        dev_keys = np.asarray(games["dev_key"], dtype=object).astype(str)
        dev = np.unique(dev_keys, return_inverse=True)[1]
        held = leaveout.mix_effects(base, members["cid"], rows, dev, raw.num_rows)
        raw = raw.rename_columns(
            ["shared_effect" if c == "effect" else c for c in raw.column_names]
        )
        raw = raw.set_column(
            raw.column_names.index("mean_predicted"),
            "mean_predicted",
            pa.array(held["mean_predicted"]),
        )
        raw = raw.set_column(
            raw.column_names.index("resid_var"), "resid_var", pa.array(held["resid_var"])
        )
        raw = raw.append_column("effect", pa.array(held["effect"]))
        n = raw["n_devs"].to_numpy()
        st = combos.effect_stats(n, held["effect"], held["resid_var"], cfg.ci_level)
        size = raw["size"].to_numpy()
        q = np.empty(len(n))
        for s in (2, 3):
            m = size == s
            q[m] = combos.bh_qvalues(st["p_value"][m])
        combos_tbl = raw.drop_columns(["resid_var", "cid"])  # noqa: F841
        for k, v in {**st, "q_value": q}.items():
            combos_tbl = combos_tbl.append_column(k, pa.array(v))
        con.execute(
            """
            CREATE OR REPLACE TABLE combos AS
            SELECT c.*,
                   c.mean_score - (s1.mean_score + s2.mean_score + COALESCE(s3.mean_score, 0))
                       / c.size AS naive_lift,
                   EXISTS (
                       SELECT 1 FROM synonym_pairs sp
                       WHERE (sp.t1 = c.t1 AND sp.t2 = c.t2) OR (sp.t1 = c.t1 AND sp.t2 = c.t3)
                          OR (sp.t1 = c.t2 AND sp.t2 = c.t3)
                   ) AS has_synonym
            FROM combos_tbl c
            JOIN tag_stats s1 ON s1.tagid = c.t1
            JOIN tag_stats s2 ON s2.tagid = c.t2
            LEFT JOIN tag_stats s3 ON s3.tagid = c.t3
            """
        )
        summary = con.execute(
            """
            SELECT size, COUNT(*) AS combos,
                   SUM((q_value < 0.1)::INT) AS significant,
                   SUM((has_synonym)::INT) AS with_synonym
            FROM combos GROUP BY size ORDER BY size
            """
        ).fetchall()
        recovery = _validate(base, X, y, fit.alpha, raw, members, rows)
        log(
            f"planted +{recovery['planted_pp']:.1f} pp on {recovery['n']} pairs: recovered "
            f"{100 * recovery['recovery_median']:.0f}% (shared baseline "
            f"{100 * recovery['shared_recovery_median']:.0f}%)"
        )
        info = {
            "analyzed_at": datetime.now(UTC).isoformat(),
            "n_games": n_games,
            "prior_alpha": prior.alpha,
            "prior_beta": prior.beta,
            "ridge_alpha": fit.alpha,
            "r2": fit.r2,
            "cv_r2": fit.cv_r2,
            "min_support": cfg.min_support,
            "min_devs": cfg.min_devs,
            "ci_level": cfg.ci_level,
            "synonym_threshold": cfg.synonym_threshold,
            **recovery,
        }
        info_tbl = pa.table({k: [v] for k, v in info.items()})  # noqa: F841
        con.execute("CREATE OR REPLACE TABLE analysis_info AS SELECT * FROM info_tbl")
        for size_, total, sig, syn in summary:
            log(
                f"{'pairs' if size_ == 2 else 'triples'}: {total:,} combos, "
                f"{sig:,} significant (q < 0.1), {syn:,} with a synonym pair"
            )
        return info
    finally:
        con.close()


def _validate(base, X, y, alpha, raw, members, rows, n=60, delta=0.4, seed=0) -> dict:
    """Plant a known interaction on random pairs and check how much each method recovers."""
    rng = np.random.default_rng(seed)
    size = raw["size"].to_numpy()
    n_games = raw["n_games"].to_numpy()
    ok = np.flatnonzero((size == 2) & (n_games >= 30) & (n_games <= 3000))
    pick = rng.choice(ok, min(n, len(ok)), replace=False)
    bounds = np.searchsorted(members["cid"], np.arange(raw.num_rows + 1))
    groups = [rows[bounds[c] : bounds[c + 1]] for c in pick]
    rec = leaveout.planted_recovery(X, y, alpha, groups, delta, seed=seed)
    true_pp = np.mean([100 * _shift(base.y[g], delta).mean() for g in groups])
    return {
        "n": len(groups),
        "planted_pp": float(true_pp),
        "recovery_median": float(np.median(rec["leave_mix_out"])),
        "recovery_p10": float(np.percentile(rec["leave_mix_out"], 10)),
        "shared_recovery_median": float(np.median(rec["shared"])),
        "shared_recovery_p10": float(np.percentile(rec["shared"], 10)),
    }


def _shift(y: np.ndarray, delta: float) -> np.ndarray:
    from scipy import special

    return special.expit(y + delta) - special.expit(y)
