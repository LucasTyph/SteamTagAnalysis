"""Additive baseline model: what score would a game get from its tags alone?

logit(score) ~ sum(tag effects) + release-year, price, popularity and early-access
controls, fitted with ridge regression. A combo's *interaction effect* is the
mean residual (actual minus predicted score, in percentage points) of the games
that have it: how much the mix beats or misses what its parts predict.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse, special
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

YEAR_MIN, YEAR_MAX = 2006, 2026
PRICE_BINS = [0.01, 5, 10, 20, 40]  # free is its own column
REVIEW_BINS = [50, 100, 300, 1_000, 3_000, 10_000, 100_000]


@dataclass
class ModelResult:
    predicted: np.ndarray  # predicted score in [0, 1]
    tag_coef: dict[int, float]  # tagid → logit-scale coefficient
    alpha: float
    r2: float  # in-sample R^2 on the logit scale
    cv_r2: float  # out-of-fold R^2 on the logit scale
    feature_names: list[str]


def _one_hot(codes: np.ndarray, n_levels: int, prefix: str) -> tuple[sparse.csr_matrix, list[str]]:
    rows = np.arange(len(codes))
    m = sparse.csr_matrix((np.ones(len(codes)), (rows, codes)), shape=(len(codes), n_levels))
    return m[:, 1:], [f"{prefix}={i}" for i in range(1, n_levels)]  # drop level 0 as reference


def design_matrix(
    game_tag_index: tuple[np.ndarray, np.ndarray],
    tagids: np.ndarray,
    n_games: int,
    year: np.ndarray,
    price: np.ndarray,
    is_free: np.ndarray,
    early_access: np.ndarray,
    review_count: np.ndarray,
) -> tuple[sparse.csr_matrix, list[str]]:
    """Sparse X: tag dummies + one-hot controls.

    game_tag_index: (game row indices, tag column indices) of relevant tags.
    """
    gi, ti = game_tag_index
    tags = sparse.csr_matrix((np.ones(len(gi)), (gi, ti)), shape=(n_games, len(tagids)))
    names = [f"tag={t}" for t in tagids]

    # Year: unknown → level 0 (reference), else clipped year
    y = np.where(np.isnan(year), 0, np.clip(year, YEAR_MIN, YEAR_MAX) - YEAR_MIN + 1).astype(int)
    year_m, year_n = _one_hot(y, YEAR_MAX - YEAR_MIN + 2, "year")

    # Price: 0 = unknown, 1 = free, 2.. = bins
    p = np.where(np.isnan(price), 0, np.digitize(np.nan_to_num(price), PRICE_BINS) + 1)
    p = np.where(is_free, 1, p).astype(int)
    price_m, price_n = _one_hot(p, len(PRICE_BINS) + 2, "price")

    r = np.digitize(review_count, REVIEW_BINS).astype(int)
    rev_m, rev_n = _one_hot(r, len(REVIEW_BINS) + 1, "reviews")

    ea = sparse.csr_matrix(early_access.astype(float).reshape(-1, 1))
    X = sparse.hstack([tags, year_m, price_m, rev_m, ea], format="csr")
    return X, names + year_n + price_n + rev_n + ["early_access"]


def logit(p: np.ndarray, eps: float = 1e-4) -> np.ndarray:
    return special.logit(np.clip(p, eps, 1 - eps))


def _r2(y: np.ndarray, yhat: np.ndarray) -> float:
    return 1 - float(((y - yhat) ** 2).sum() / ((y - y.mean()) ** 2).sum())


def fit(
    X: sparse.csr_matrix,
    score: np.ndarray,
    tagids: np.ndarray,
    feature_names: list[str],
    alphas: tuple[float, ...] = (1, 3, 10, 30, 100),
    seed: int = 0,
) -> ModelResult:
    y = logit(score)
    folds = KFold(5, shuffle=True, random_state=seed)

    def cv_r2(alpha: float) -> tuple[float, np.ndarray]:
        oof = np.empty_like(y)
        for tr, te in folds.split(X):
            m = Ridge(alpha=alpha).fit(X[tr], y[tr])
            oof[te] = m.predict(X[te])
        return _r2(y, oof), oof

    scored = [(cv_r2(a)[0], a) for a in alphas]
    best_r2, best_alpha = max(scored)
    model = Ridge(alpha=best_alpha).fit(X, y)
    yhat = model.predict(X)
    coef = model.coef_[: len(tagids)]
    return ModelResult(
        predicted=special.expit(yhat),
        tag_coef={int(t): float(c) for t, c in zip(tagids, coef, strict=True)},
        alpha=best_alpha,
        r2=_r2(y, yhat),
        cv_r2=best_r2,
        feature_names=feature_names,
    )
