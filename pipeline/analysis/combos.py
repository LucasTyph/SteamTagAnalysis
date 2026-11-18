"""Statistics for tag combinations (pairs and triples).

Inputs are per-game residuals (actual − predicted score, percentage points) from
the additive model. For each combo with enough games we report:

- n_games and n_devs, mean score, mean predicted score
- effect = mean residual across developers, with a t-based 90% CI
- p-value and Benjamini–Hochberg q-value (per combo size)
- naive_lift = mean score − mean of the single-tag mean scores
- whether the combo contains a near-synonym tag pair
"""

from __future__ import annotations

import numpy as np
from scipy import stats


def bh_qvalues(p: np.ndarray) -> np.ndarray:
    """Benjamini–Hochberg adjusted p-values."""
    p = np.asarray(p, float)
    n = len(p)
    if n == 0:
        return p
    order = np.argsort(p)
    ranked = p[order] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.minimum(q, 1.0)
    return out


def effect_stats(
    n: np.ndarray, mean: np.ndarray, var: np.ndarray, level: float = 0.90
) -> dict[str, np.ndarray]:
    """t-based CI and two-sided p-value for H0: mean residual = 0."""
    n = np.asarray(n, float)
    se = np.sqrt(np.asarray(var, float) / n)
    se = np.where(se > 0, se, np.nan)
    tcrit = stats.t.ppf(0.5 + level / 2, df=n - 1)
    t = np.asarray(mean, float) / se
    p = 2 * stats.t.sf(np.abs(t), df=n - 1)
    p = np.where(np.isnan(p), 1.0, p)
    return {
        "se": se,
        "ci_low": mean - tcrit * se,
        "ci_high": mean + tcrit * se,
        "p_value": p,
    }


# Games from one developer aren't independent (asset-flip series, sequels), so each
# developer counts once per combo: average its games first, then compute statistics
# across developers. n_games is reported too, but the CI and p-value use n_devs.
_AGGREGATE = """
SELECT t1, t2, t3, size,
       SUM(dev_games)::BIGINT AS n_games,
       COUNT(*) AS n_devs,
       AVG(dev_score) AS mean_score, AVG(dev_predicted) AS mean_predicted,
       AVG(dev_resid) AS effect, VAR_SAMP(dev_resid) AS resid_var,
       MEDIAN(dev_reviews) AS median_reviews, MEDIAN(dev_year) AS median_year
FROM per_dev
GROUP BY t1, t2, t3, size
HAVING SUM(dev_games) >= $min_support AND COUNT(*) >= $min_devs
"""

_PER_DEV = """
COUNT(*) AS dev_games, AVG(a.score) AS dev_score, AVG(a.predicted) AS dev_predicted,
AVG(a.resid) AS dev_resid, MEDIAN(a.review_count) AS dev_reviews, MEDIAN(a.year) AS dev_year
"""

PAIR_SQL = f"""
WITH per_dev AS (
  SELECT a.tagid AS t1, b.tagid AS t2, NULL::BIGINT AS t3, 2 AS size, a.dev_key, {_PER_DEV}
  FROM rel a JOIN rel b ON a.appid = b.appid AND a.tagid < b.tagid
  GROUP BY a.tagid, b.tagid, a.dev_key
)
{_AGGREGATE}
"""

TRIPLE_SQL = f"""
WITH per_dev AS (
  SELECT a.tagid AS t1, b.tagid AS t2, c.tagid AS t3, 3 AS size, a.dev_key, {_PER_DEV}
  FROM rel a
  JOIN rel b ON a.appid = b.appid AND a.tagid < b.tagid
  JOIN rel c ON a.appid = c.appid AND b.tagid < c.tagid
  GROUP BY a.tagid, b.tagid, c.tagid, a.dev_key
)
{_AGGREGATE}
"""

SYNONYM_SQL = """
WITH n AS (SELECT tagid, COUNT(*) AS n FROM rel GROUP BY tagid)
SELECT a.tagid AS t1, b.tagid AS t2
FROM rel a JOIN rel b ON a.appid = b.appid AND a.tagid < b.tagid
JOIN n na ON na.tagid = a.tagid JOIN n nb ON nb.tagid = b.tagid
GROUP BY a.tagid, b.tagid, na.n, nb.n
HAVING LEAST(COUNT(*) / na.n, COUNT(*) / nb.n) >= $threshold
"""
