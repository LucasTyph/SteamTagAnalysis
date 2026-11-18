import numpy as np
import pytest

from pipeline.analysis import combos, model, shrinkage


def test_fit_prior_recovers_beta_parameters():
    rng = np.random.default_rng(0)
    p = rng.beta(8, 2, size=20_000)
    n = rng.integers(20, 2_000, size=p.size)
    k = rng.binomial(n, p)
    prior = shrinkage.fit_prior(k, n)
    assert prior.mean == pytest.approx(0.8, abs=0.01)
    assert prior.strength == pytest.approx(10, rel=0.15)


def test_posterior_shrinks_small_games_more():
    prior = shrinkage.BetaPrior(alpha=8, beta=2)
    small, big = shrinkage.posterior_mean(np.array([20, 20_000]), np.array([20, 20_000]), prior)
    assert small == pytest.approx(28 / 30)
    assert big > small  # 100% positive with more evidence stays closer to 1


def test_bh_qvalues_matches_reference():
    p = np.array([0.01, 0.04, 0.03, 0.20])
    # reference: statsmodels multipletests(method="fdr_bh")
    np.testing.assert_allclose(combos.bh_qvalues(p), [0.04, 0.0533333, 0.0533333, 0.2], rtol=1e-5)


def test_effect_stats_ci_contains_mean_and_p_value_sane():
    st = combos.effect_stats(np.array([30, 30]), np.array([5.0, 0.0]), np.array([100.0, 100.0]))
    assert st["ci_low"][0] < 5 < st["ci_high"][0]
    assert st["p_value"][0] < 0.05 < st["p_value"][1]


def test_model_finds_planted_interaction():
    """Tags A and B each have no effect alone, but games with both score higher."""
    rng = np.random.default_rng(1)
    n_games, tagids = 6_000, np.array([1, 2, 3])
    has = rng.random((n_games, 3)) < 0.3
    gi, ti = np.nonzero(has)
    logit_score = 1.2 + 0.4 * has[:, 2] + 0.8 * (has[:, 0] & has[:, 1])
    score = 1 / (1 + np.exp(-(logit_score + rng.normal(0, 0.3, n_games))))
    X, names = model.design_matrix(
        (gi, ti),
        tagids,
        n_games,
        year=np.full(n_games, 2020.0),
        price=np.full(n_games, 9.99),
        is_free=np.zeros(n_games, bool),
        early_access=np.zeros(n_games, bool),
        review_count=np.full(n_games, 500),
    )
    fit = model.fit(X, score, tagids, names)
    assert fit.tag_coef[3] == pytest.approx(0.4, abs=0.05)
    resid = score - fit.predicted
    both = has[:, 0] & has[:, 1]
    # The additive model absorbs part of the interaction into A's and B's own
    # coefficients, so the residual effect is attenuated (conservative), but clearly > 0.
    assert resid[both].mean() > 0.02
    assert resid[both].mean() > resid[~both].mean() + 0.03
    assert abs(resid[has[:, 2] & ~both].mean()) < 0.01  # an additive tag shows no interaction


def test_run_clusters_combo_stats_by_developer(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    from pipeline.analysis import run as analysis
    from pipeline.config import AnalysisConfig, BuildConfig

    rng = np.random.default_rng(2)
    rows, tag_rows = [], []
    appid = 0
    # 40 independent developers with random tag subsets of {1, 2, 3}
    for d in range(40):
        for _ in range(3):
            appid += 1
            n = int(rng.integers(30, 500))
            rows.append((appid, int(n * rng.uniform(0.6, 0.95)), n, f"clan:{d}"))
            for t in (1, 2, 3):
                if rng.random() < 0.6:
                    tag_rows.append((appid, t))
    # One studio ships 20 near-identical, very well-rated games tagged 1 + 2
    for _ in range(20):
        appid += 1
        rows.append((appid, 99, 100, "clan:series"))
        tag_rows += [(appid, 1), (appid, 2)]

    path = tmp_path / "a.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE games (appid BIGINT, n_pos BIGINT, review_count BIGINT, dev_key VARCHAR, "
        "first_release TIMESTAMP, price_usd DOUBLE, is_free BOOLEAN, is_early_access BOOLEAN)"
    )
    con.executemany(
        "INSERT INTO games VALUES (?, ?, ?, ?, TIMESTAMP '2020-01-01', 9.99, false, false)", rows
    )
    con.execute("CREATE TABLE game_tags (appid BIGINT, tagid BIGINT, relevant BOOLEAN)")
    con.executemany("INSERT INTO game_tags VALUES (?, ?, true)", tag_rows)
    con.execute("CREATE TABLE tags (tagid BIGINT, name VARCHAR)")
    con.executemany("INSERT INTO tags VALUES (?, ?)", [(1, "A"), (2, "B"), (3, "C")])
    con.close()

    analysis.run(path, AnalysisConfig(min_support=5, min_devs=3), BuildConfig(), log=lambda m: None)
    con = duckdb.connect(str(path), read_only=True)
    n_games, n_devs = con.execute(
        "SELECT n_games, n_devs FROM combos WHERE t1 = 1 AND t2 = 2 AND t3 IS NULL"
    ).fetchone()
    expected_devs = (
        1
        + con.execute(
            """SELECT COUNT(DISTINCT g.dev_key) FROM games g
           WHERE g.dev_key <> 'clan:series'
             AND appid IN (SELECT appid FROM game_tags WHERE tagid = 1)
             AND appid IN (SELECT appid FROM game_tags WHERE tagid = 2)"""
        ).fetchone()[0]
    )
    assert n_devs == expected_devs  # the 20-game series counts as one developer
    assert n_games >= 20 + n_devs - 1
    assert con.execute("SELECT COUNT(*) FROM game_scores").fetchone()[0] == len(rows)
