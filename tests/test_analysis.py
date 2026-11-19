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


def _months(n, start=(2020, 1)):
    from datetime import date

    from pipeline.analysis.timelines import _add_months

    return [_add_months(date(*start, 1), i) for i in range(n)]


def test_timeline_detects_planted_drop_and_recovery():
    from pipeline.analysis.timelines import summarize

    rng = np.random.default_rng(3)
    p = np.r_[np.full(12, 0.90), np.full(8, 0.60), np.full(12, 0.85)]
    n = np.full(len(p), 400)
    up = rng.binomial(n, p)
    s = summarize(_months(len(p)), list(up), list(n - up))
    assert len(s.changes) == 2
    assert s.changes[0].month == _months(len(p))[12] and s.changes[0].shift < -20
    assert s.changes[1].month == _months(len(p))[20] and s.changes[1].shift > 15
    assert s.launch_score == pytest.approx(90, abs=3)
    assert s.recent_score == pytest.approx(85, abs=3)
    assert s.trough_score == pytest.approx(60, abs=4)
    assert s.recovery > 20


def test_timeline_stable_series_has_no_changes_and_handles_gaps():
    from pipeline.analysis.timelines import summarize

    rng = np.random.default_rng(4)
    months = _months(30)
    n = np.full(30, 300)
    up = rng.binomial(n, 0.8)
    # drop two months entirely (no reviews) — they get filled with zeros
    keep = [i for i in range(30) if i not in (10, 11)]
    s = summarize([months[i] for i in keep], list(up[keep]), list((n - up)[keep]))
    assert s.changes == []
    assert s.months == 30
    assert s.volatility < 5


def test_match_news_prefers_closest_update_within_window():
    from datetime import date, datetime

    from pipeline.analysis.timelines import NewsItem, match_news

    news = [
        NewsItem(datetime(2021, 3, 1), "Big patch", "u1", "update"),
        NewsItem(datetime(2021, 3, 14), "Dev stream", "u2", "other"),
        NewsItem(datetime(2021, 5, 20), "Season 2", "u3", "update"),
    ]
    assert match_news(date(2021, 3, 1), news).url == "u1"
    assert match_news(date(2021, 9, 1), news) is None


def test_launch_window_extends_until_enough_reviews():
    from pipeline.analysis.timelines import summarize

    # 3 tiny all-positive months, then normal volume at 70%
    up = [2, 3, 1] + [140] * 12
    down = [0, 0, 0] + [60] * 12
    s = summarize(_months(15), up, down)
    assert s.launch_score == pytest.approx(70.6, abs=1)  # not 100%
    assert summarize(_months(15), up, down, launched_before_reviews=True).launch_score is None


def _planted_data(seed=1, n_games=6_000):
    rng = np.random.default_rng(seed)
    tagids = np.array([1, 2, 3])
    has = rng.random((n_games, 3)) < 0.3
    gi, ti = np.nonzero(has)
    logit_score = 1.2 + 0.4 * has[:, 2] + 0.8 * (has[:, 0] & has[:, 1])
    score = 1 / (1 + np.exp(-(logit_score + rng.normal(0, 0.3, n_games))))
    X, _ = model.design_matrix(
        (gi, ti),
        tagids,
        n_games,
        year=rng.integers(2015, 2025, n_games).astype(float),
        price=np.full(n_games, 9.99),
        is_free=np.zeros(n_games, bool),
        early_access=np.zeros(n_games, bool),
        review_count=rng.integers(20, 5000, n_games),
    )
    return X, score, has


@pytest.mark.parametrize("small", [0, 10_000])
def test_leave_mix_out_matches_a_real_refit(monkeypatch, small):
    from scipy import sparse

    from pipeline.analysis import leaveout

    monkeypatch.setattr(leaveout, "SMALL_MIX", small)  # exercise both code paths
    X, score, has = _planted_data(n_games=1_500)
    y = model.logit(score)
    base = leaveout.Baseline.fit(X, y, alpha=10)
    rows = np.flatnonzero(has[:, 0] & has[:, 1])
    pred, resid = base.held_out(rows)

    keep = np.setdiff1d(np.arange(len(y)), rows)
    refit = leaveout.Baseline.fit(X[keep], y[keep], alpha=10)
    X1 = sparse.hstack([sparse.csr_matrix(np.ones((len(rows), 1))), X[rows]], format="csr")
    direct = 1 / (1 + np.exp(-(X1 @ refit.beta)))
    np.testing.assert_allclose(pred, direct, rtol=1e-8)
    np.testing.assert_allclose(resid, score[rows] - direct, rtol=1e-6, atol=1e-10)


def test_leave_mix_out_recovers_the_full_planted_interaction():
    from pipeline.analysis import leaveout

    X, score, has = _planted_data()
    y = model.logit(score)
    base = leaveout.Baseline.fit(X, y, alpha=10)
    both = np.flatnonzero(has[:, 0] & has[:, 1])
    # The planted effect in score units: the same games without the +0.8 logit bump.
    true = np.mean(score[both] - 1 / (1 + np.exp(-(y[both] - 0.8))))
    shared = np.mean(base.score[both] - base.predicted[both])
    held = base.held_out(both)[1].mean()
    assert shared < 0.75 * true  # the shared baseline absorbs a good part of it
    assert held == pytest.approx(true, rel=0.1)


def test_mix_effects_cluster_by_developer():
    from pipeline.analysis import leaveout

    X, score, has = _planted_data(n_games=2_000)
    base = leaveout.Baseline.fit(X, model.logit(score), alpha=10)
    rows = np.flatnonzero(has[:, 0] & has[:, 1])
    dev = np.arange(len(score)) // 4  # four games per developer
    out = leaveout.mix_effects(base, np.zeros(len(rows), int), rows, dev, 1)
    pred, resid = base.held_out(rows)
    per_dev = [resid[dev[rows] == d].mean() for d in np.unique(dev[rows])]
    assert out["effect"][0] == pytest.approx(100 * np.mean(per_dev))
    assert out["resid_var"][0] == pytest.approx(100**2 * np.var(per_dev, ddof=1))
